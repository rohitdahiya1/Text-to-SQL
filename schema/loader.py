"""
schema/loader.py

Loads the full schema metadata (tables, columns, PKs, FKs) from Supabase
at application startup and caches it in memory.

Two sources of truth:
  1. Supabase information_schema → actual column types, PK/FK relationships (authoritative)
  2. SCHEMA_DESCRIPTIONS (below) → human-written semantic descriptions for each table/column
     These descriptions are what get embedded into FAISS for retrieval.

When you add a new table to your DB:
  1. Add its entry to SCHEMA_DESCRIPTIONS below
  2. Call `build_faiss_index()` in schema/embedder.py to rebuild the index
"""

from __future__ import annotations
import logging
from supabase import create_client, Client
import config

logger = logging.getLogger(__name__)

# ── Semantic descriptions ─────────────────────────────────────────────────────
# Written once, used for FAISS embedding. Include business aliases so that
# user terminology like "revenue", "clients", "purchases" retrieves the right tables.

SCHEMA_DESCRIPTIONS: dict[str, dict] = {
    "regions": {
        "description": "Geographic regions of India. Lookup table used to group customers and orders by area. Aliases: zone, area, territory.",
        "columns": {
            "region_id":   "Primary key. Unique integer identifier for the region.",
            "region_name": "Name of the region (North, South, East, West, Central, Northeast).",
            "country":     "Country name. Always 'India' in current data.",
        }
    },
    "customers": {
        "description": "Master table of all registered customers/buyers/users/clients. Contains personal details and account status.",
        "columns": {
            "customer_id":   "Primary key. Unique customer identifier.",
            "full_name":     "Customer's full name.",
            "email":         "Customer's email address. Unique.",
            "phone":         "Customer's phone number.",
            "gender":        "Gender of the customer: Male, Female, or Other.",
            "date_of_birth": "Customer's date of birth. Used for age-based analysis.",
            "created_at":    "Timestamp when the customer account was created (registration date).",
            "is_active":     "Boolean flag. True if the customer account is active.",
        }
    },
    "addresses": {
        "description": "Delivery and billing addresses for customers. Each customer can have multiple addresses. Linked to regions for geographic analysis. Aliases: location, delivery address, shipping address.",
        "columns": {
            "address_id":   "Primary key.",
            "customer_id":  "Foreign key to customers. Which customer owns this address.",
            "region_id":    "Foreign key to regions. Geographic region of this address.",
            "address_line": "Street address line.",
            "city":         "City name. Used for city-level filtering and grouping.",
            "state":        "State name. Used for state-level filtering and grouping.",
            "pincode":      "6-digit postal code.",
            "address_type": "Type of address: Home, Work, or Other.",
            "is_default":   "True if this is the customer's default address.",
        }
    },
    "categories": {
        "description": "Product category hierarchy. Supports parent-child structure (e.g., Electronics > Mobile Phones). Used to group and filter products by type.",
        "columns": {
            "category_id":   "Primary key.",
            "category_name": "Name of the category (e.g., Electronics, Clothing, Mobile Phones).",
            "parent_id":     "Self-referential FK. References parent category. NULL for top-level categories.",
            "description":   "Human-readable description of what the category contains.",
        }
    },
    "products": {
        "description": "Product catalog. Contains all items/goods sold on the platform. Includes pricing, brand, and SKU. Aliases: items, goods, merchandise, SKU.",
        "columns": {
            "product_id":   "Primary key.",
            "category_id":  "Foreign key to categories.",
            "product_name": "Full name of the product.",
            "brand":        "Brand or manufacturer name.",
            "sku":          "Stock-keeping unit. Unique product code.",
            "unit_price":   "Selling price per unit. Also called price, MRP, or rate.",
            "cost_price":   "Cost to procure this product. Used for margin/profit calculation.",
            "is_active":    "True if the product is currently listed for sale.",
            "created_at":   "When the product was first listed.",
        }
    },
    "product_inventory": {
        "description": "Stock/inventory levels for each product. Tracks available quantity and reorder thresholds. Aliases: stock, inventory, warehouse.",
        "columns": {
            "inventory_id":      "Primary key.",
            "product_id":        "Foreign key to products. One-to-one relationship.",
            "quantity_in_stock": "Current available stock quantity.",
            "reorder_level":     "Minimum stock level before restocking is triggered. Low stock = quantity_in_stock <= reorder_level.",
            "last_restocked_at": "Timestamp of last inventory replenishment.",
        }
    },
    "orders": {
        "description": "Order header table. One row per customer order/purchase/transaction. Contains revenue/sales totals, order status, and delivery info. Aliases: purchases, transactions, sales.",
        "columns": {
            "order_id":        "Primary key.",
            "customer_id":     "Foreign key to customers. Who placed the order.",
            "address_id":      "Foreign key to addresses. Delivery address for this order.",
            "order_status":    "Current status: pending, confirmed, shipped, delivered, cancelled, returned.",
            "total_amount":    "Total order value including all items. Represents revenue or sales.",
            "discount_amount": "Discount applied on this order.",
            "shipping_charge": "Shipping fee charged to the customer.",
            "created_at":      "When the order was placed (order date).",
            "delivered_at":    "When the order was delivered. NULL if not yet delivered.",
        }
    },
    "order_items": {
        "description": "Line items for each order. Bridge table between orders and products. One row per product per order. Use to find which products were bought, quantities, and subtotals.",
        "columns": {
            "order_item_id": "Primary key.",
            "order_id":      "Foreign key to orders.",
            "product_id":    "Foreign key to products.",
            "quantity":      "Number of units ordered.",
            "unit_price":    "Price per unit at the time of order (may differ from current product price).",
            "subtotal":      "Computed column: quantity * unit_price. Total for this line item.",
        }
    },
    "payments": {
        "description": "Payment records. One payment per order. Tracks how the order was paid and payment status. Aliases: transactions, receipts, payment method.",
        "columns": {
            "payment_id":     "Primary key.",
            "order_id":       "Foreign key to orders. One-to-one.",
            "payment_method": "How the order was paid: UPI, Credit Card, Debit Card, Net Banking, COD, Wallet.",
            "payment_status": "Status of payment: pending, success, failed, refunded.",
            "paid_amount":    "Actual amount paid by customer.",
            "transaction_id": "Payment gateway transaction reference ID.",
            "paid_at":        "Timestamp when payment was completed.",
        }
    },
    "reviews": {
        "description": "Product reviews and ratings submitted by customers after purchase. Linked to product, customer, and the specific order. Aliases: feedback, ratings, testimonials.",
        "columns": {
            "review_id":   "Primary key.",
            "product_id":  "Foreign key to products. Which product is being reviewed.",
            "customer_id": "Foreign key to customers. Who wrote the review.",
            "order_id":    "Foreign key to orders. The order that included this product.",
            "rating":      "Numeric rating from 1 (worst) to 5 (best).",
            "title":       "Short title of the review.",
            "body":        "Full review text.",
            "created_at":  "When the review was submitted.",
        }
    },
}


# ── Runtime cache (populated at startup) ────────────────────────────────────
_schema_cache: dict | None = None


def get_supabase_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def load_schema() -> dict:
    """
    Loads schema metadata from Supabase information_schema and merges with
    SCHEMA_DESCRIPTIONS. Result is cached in memory for the lifetime of the process.

    Returns a dict keyed by table_name:
    {
        "orders": {
            "description": "...",
            "columns": [
                {
                    "name": "order_id",
                    "type": "integer",
                    "description": "...",
                    "is_pk": True,
                    "is_fk": False,
                    "references": None
                },
                ...
            ]
        },
        ...
    }
    """
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    logger.info("Loading schema metadata from Supabase...")
    client = get_supabase_client()

    # ── 1. Fetch column info ──────────────────────────────────────────────────
    columns_response = client.rpc("get_schema_columns").execute()
    # Falls back to raw SQL if RPC not set up (see note below)
    # We query information_schema directly via a raw SQL helper
    raw_columns = _fetch_columns(client)
    raw_fks      = _fetch_foreign_keys(client)
    raw_pks      = _fetch_primary_keys(client)

    # Build PK lookup: table → set of pk column names
    pk_map: dict[str, set] = {}
    for pk in raw_pks:
        pk_map.setdefault(pk["table_name"], set()).add(pk["column_name"])

    # Build FK lookup: (table, column) → {"references_table", "references_column"}
    fk_map: dict[tuple, dict] = {}
    for fk in raw_fks:
        fk_map[(fk["table_name"], fk["column_name"])] = {
            "references_table":  fk["foreign_table_name"],
            "references_column": fk["foreign_column_name"],
        }

    # ── 2. Assemble schema dict ──────────────────────────────────────────────
    schema: dict = {}
    for row in raw_columns:
        tbl = row["table_name"]
        col = row["column_name"]
        if tbl not in schema:
            desc_entry = SCHEMA_DESCRIPTIONS.get(tbl, {})
            schema[tbl] = {
                "description": desc_entry.get("description", f"Table: {tbl}"),
                "columns": []
            }

        col_desc = SCHEMA_DESCRIPTIONS.get(tbl, {}).get("columns", {}).get(col, "")
        is_pk = col in pk_map.get(tbl, set())
        fk_info = fk_map.get((tbl, col))

        schema[tbl]["columns"].append({
            "name":              col,
            "type":              row["data_type"],
            "description":       col_desc,
            "is_pk":             is_pk,
            "is_fk":             fk_info is not None,
            "references_table":  fk_info["references_table"]  if fk_info else None,
            "references_column": fk_info["references_column"] if fk_info else None,
        })

    _schema_cache = schema
    logger.info(f"Schema loaded: {len(schema)} tables.")
    return schema


def _fetch_columns(client: Client) -> list[dict]:
    """Fetch column metadata from information_schema."""
    result = client.from_("information_schema.columns") \
        .select("table_name, column_name, data_type, ordinal_position") \
        .eq("table_schema", "public") \
        .order("table_name") \
        .order("ordinal_position") \
        .execute()
    return result.data


def _fetch_primary_keys(client: Client) -> list[dict]:
    """Fetch primary key columns via information_schema."""
    # Supabase postgrest doesn't support direct joins in information_schema well,
    # so we use the pg_constraint approach via a raw SQL RPC.
    # Create this function once in Supabase SQL editor:
    #
    # CREATE OR REPLACE FUNCTION get_primary_keys()
    # RETURNS TABLE(table_name text, column_name text) AS $$
    #   SELECT kcu.table_name::text, kcu.column_name::text
    #   FROM information_schema.key_column_usage kcu
    #   JOIN information_schema.table_constraints tc
    #     ON kcu.constraint_name = tc.constraint_name
    #    AND kcu.table_schema    = tc.table_schema
    #   WHERE tc.constraint_type = 'PRIMARY KEY'
    #     AND kcu.table_schema   = 'public';
    # $$ LANGUAGE sql SECURITY DEFINER;
    result = client.rpc("get_primary_keys").execute()
    return result.data


def _fetch_foreign_keys(client: Client) -> list[dict]:
    """Fetch FK relationships via RPC (defined once in Supabase).
    
    Create this function once in Supabase SQL editor:

    CREATE OR REPLACE FUNCTION get_foreign_keys()
    RETURNS TABLE(
        table_name         text,
        column_name        text,
        foreign_table_name text,
        foreign_column_name text
    ) AS $$
        SELECT
            kcu.table_name::text,
            kcu.column_name::text,
            ccu.table_name::text  AS foreign_table_name,
            ccu.column_name::text AS foreign_column_name
        FROM information_schema.referential_constraints rc
        JOIN information_schema.key_column_usage kcu
          ON kcu.constraint_name = rc.constraint_name
         AND kcu.constraint_schema = rc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = rc.unique_constraint_name
         AND ccu.constraint_schema = rc.unique_constraint_schema
        WHERE kcu.table_schema = 'public';
    $$ LANGUAGE sql SECURITY DEFINER;
    """
    result = client.rpc("get_foreign_keys").execute()
    return result.data


def get_cached_schema() -> dict:
    """Returns the cached schema. Must call load_schema() first."""
    if _schema_cache is None:
        raise RuntimeError("Schema not loaded. Call load_schema() at startup.")
    return _schema_cache


def invalidate_cache() -> None:
    """Call this if schema changes at runtime to force reload on next access."""
    global _schema_cache
    _schema_cache = None
    logger.info("Schema cache invalidated.")