"""
glossary/terms.py
Business synonym/alias map for the e-commerce domain.
Maps natural language terms users might say → actual column or table identifiers.
This is used in Layer 1 (IR extraction) and Layer 2 (schema retrieval) to
bridge the gap between how users speak and how the database is named.

Structure:
  TERM_MAP = {
      "<user term>": {
          "table":  "<actual table name>",
          "column": "<actual column name>",   # optional
          "notes":  "<human note for LLM>"    # optional context injected into prompt
      }
  }
"""

TERM_MAP: dict[str, dict] = {

    # ── Revenue / Money ─────────────────────────────────────────────────────
    "revenue": {
        "table":  "orders",
        "column": "total_amount",
        "notes":  "Revenue means the total_amount on orders. For net revenue, subtract discount_amount."
    },
    "sales": {
        "table":  "orders",
        "column": "total_amount",
        "notes":  "Sales refers to total_amount on the orders table."
    },
    "gross revenue": {
        "table":  "orders",
        "column": "total_amount",
        "notes":  "Gross revenue = total_amount before discounts."
    },
    "net revenue": {
        "table":  "orders",
        "column": "total_amount",
        "notes":  "Net revenue = total_amount - discount_amount on orders."
    },
    "income": {
        "table":  "orders",
        "column": "total_amount",
        "notes":  "Income in this context means order revenue (total_amount)."
    },
    "amount paid": {
        "table":  "payments",
        "column": "paid_amount",
        "notes":  "Amount paid refers to paid_amount in the payments table."
    },
    "profit": {
        "table":  "order_items",
        "column": "subtotal",
        "notes":  "Profit = (unit_price - cost_price) * quantity. Requires joining order_items with products."
    },

    # ── Orders ───────────────────────────────────────────────────────────────
    "purchase": {
        "table": "orders",
        "notes": "Purchase = an order record in the orders table."
    },
    "transaction": {
        "table": "orders",
        "notes": "Transaction often refers to either orders or payments. Default to orders unless payment context is clear."
    },
    "order date": {
        "table":  "orders",
        "column": "created_at",
        "notes":  "Order date = created_at on the orders table."
    },
    "placed on": {
        "table":  "orders",
        "column": "created_at",
        "notes":  "Placed on = created_at on orders."
    },
    "delivery date": {
        "table":  "orders",
        "column": "delivered_at",
        "notes":  "Delivery date = delivered_at on orders."
    },

    # ── Order Status ─────────────────────────────────────────────────────────
    "completed orders": {
        "table":  "orders",
        "column": "order_status",
        "notes":  "Completed orders = order_status = 'delivered'."
    },
    "successful orders": {
        "table":  "orders",
        "column": "order_status",
        "notes":  "Successful orders = order_status = 'delivered'."
    },
    "failed orders": {
        "table":  "orders",
        "column": "order_status",
        "notes":  "Failed orders = order_status IN ('cancelled', 'returned')."
    },
    "open orders": {
        "table":  "orders",
        "column": "order_status",
        "notes":  "Open orders = order_status IN ('pending', 'confirmed', 'shipped')."
    },
    "refunded": {
        "table":  "payments",
        "column": "payment_status",
        "notes":  "Refunded = payment_status = 'refunded' in payments table."
    },

    # ── Customers ────────────────────────────────────────────────────────────
    "client": {
        "table": "customers",
        "notes": "Client = a customer in the customers table."
    },
    "buyer": {
        "table": "customers",
        "notes": "Buyer = customer in the customers table."
    },
    "user": {
        "table": "customers",
        "notes": "User = customer in the customers table."
    },
    "customer name": {
        "table":  "customers",
        "column": "full_name",
        "notes":  "Customer name = full_name in the customers table."
    },

    # ── Products ─────────────────────────────────────────────────────────────
    "item": {
        "table": "products",
        "notes": "Item = product in the products table."
    },
    "product price": {
        "table":  "products",
        "column": "unit_price",
        "notes":  "Product price = unit_price in the products table."
    },
    "selling price": {
        "table":  "products",
        "column": "unit_price",
        "notes":  "Selling price = unit_price in the products table."
    },
    "cost": {
        "table":  "products",
        "column": "cost_price",
        "notes":  "Cost = cost_price in the products table (what we paid the supplier)."
    },
    "margin": {
        "table":  "products",
        "column": "unit_price",
        "notes":  "Margin = unit_price - cost_price in products. Expressed as amount or percentage."
    },

    # ── Inventory ────────────────────────────────────────────────────────────
    "stock": {
        "table":  "product_inventory",
        "column": "quantity_in_stock",
        "notes":  "Stock = quantity_in_stock in the product_inventory table."
    },
    "in stock": {
        "table":  "product_inventory",
        "column": "quantity_in_stock",
        "notes":  "In stock = quantity_in_stock > 0."
    },
    "out of stock": {
        "table":  "product_inventory",
        "column": "quantity_in_stock",
        "notes":  "Out of stock = quantity_in_stock = 0 or below reorder_level."
    },
    "low stock": {
        "table":  "product_inventory",
        "column": "quantity_in_stock",
        "notes":  "Low stock = quantity_in_stock <= reorder_level in product_inventory."
    },

    # ── Reviews / Ratings ────────────────────────────────────────────────────
    "rating": {
        "table":  "reviews",
        "column": "rating",
        "notes":  "Rating = rating column in reviews table (1–5 scale)."
    },
    "review": {
        "table": "reviews",
        "notes": "Review = a row in the reviews table."
    },
    "average rating": {
        "table":  "reviews",
        "column": "rating",
        "notes":  "Average rating = AVG(rating) from the reviews table."
    },

    # ── Geography ────────────────────────────────────────────────────────────
    "region": {
        "table":  "regions",
        "column": "region_name",
        "notes":  "Region = region_name in the regions table. Joined via addresses."
    },
    "location": {
        "table":  "addresses",
        "column": "city",
        "notes":  "Location can mean city or state in the addresses table."
    },
    "city": {
        "table":  "addresses",
        "column": "city",
        "notes":  "City = city column in the addresses table."
    },
    "state": {
        "table":  "addresses",
        "column": "state",
        "notes":  "State = state column in the addresses table."
    },

    # ── Payment ──────────────────────────────────────────────────────────────
    "payment mode": {
        "table":  "payments",
        "column": "payment_method",
        "notes":  "Payment mode = payment_method in payments (UPI, Credit Card, COD, etc.)."
    },
    "upi": {
        "table":  "payments",
        "column": "payment_method",
        "notes":  "UPI = payment_method = 'UPI' in the payments table."
    },
    "cod": {
        "table":  "payments",
        "column": "payment_method",
        "notes":  "COD = payment_method = 'COD' (Cash on Delivery) in payments."
    },
}


def resolve_terms(entities: list[str]) -> list[dict]:
    """
    Takes a list of entity strings from the IR and returns enriched
    entity dicts with table/column mappings where known.
    Unknown terms are passed through unchanged so the LLM can still attempt them.
    """
    resolved = []
    for entity in entities:
        key = entity.lower().strip()
        if key in TERM_MAP:
            resolved.append({
                "original":  entity,
                "resolved":  True,
                **TERM_MAP[key]
            })
        else:
            resolved.append({
                "original": entity,
                "resolved": False,
                "notes":    f"No glossary mapping found for '{entity}'. LLM will infer from schema."
            })
    return resolved