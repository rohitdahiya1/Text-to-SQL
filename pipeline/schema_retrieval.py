"""
pipeline/schema_retrieval.py  —  Layer 2

Retrieves the most relevant tables for a query using FAISS semantic search,
then enriches them with full column metadata from the in-memory schema cache.

Also performs a reachability filter: if retrieved tables are not connected
by FK paths, adds the minimum necessary bridge tables automatically.

Output is a trimmed schema context (~8–15 tables) ready for LLM consumption.
This avoids passing all 100+ tables to the LLM, saving tokens and reducing
hallucination from irrelevant schema noise.
"""

from __future__ import annotations
import logging

import config
from models.schemas import IntermediateRepresentation, RetrievedSchema
from schema.embedder import search_tables
from schema.loader import get_cached_schema
from schema.graph import _graph   # access adjacency list for reachability

logger = logging.getLogger(__name__)


def retrieve_relevant_schema(
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
) -> tuple[RetrievedSchema, bool, str | None]:
    """
    Retrieves relevant tables for a query.

    Args:
        ir: The structured IR from Layer 1.
        resolved_entities: Entities with glossary mappings (from glossary/terms.py).

    Returns:
        (schema, retrieval_failed, reason)
        - schema: RetrievedSchema with table metadata
        - retrieval_failed: True if top similarity score is below threshold
        - reason: Human-readable reason string if retrieval_failed
    """
    # ── Build a rich search query from IR ────────────────────────────────────
    # Use resolved glossary table names + raw entities + IR intent for best retrieval
    search_parts = []

    for entity in resolved_entities:
        if entity["resolved"] and "table" in entity:
            search_parts.append(entity["table"])   # use actual table name (high signal)
        search_parts.append(entity["original"])     # also include raw term

    search_parts.extend(ir.operations)
    search_parts.append(ir.intent)

    # Add any filter column hints
    for f in ir.filters:
        if f.get("column_hint"):
            search_parts.append(f["column_hint"])

    search_query = " ".join(search_parts)
    logger.debug(f"[Layer 2] FAISS search query: '{search_query}'")

    # ── FAISS search ─────────────────────────────────────────────────────────
    candidates = search_tables(search_query, top_k=config.TOP_K_TABLES)

    if not candidates:
        return (
            RetrievedSchema(tables=[], similarity_scores={}),
            True,
            f"No relevant tables found for your query. The system could not match your question to any known tables. "
            f"Could you rephrase using more specific terms (e.g., 'orders', 'customers', 'products')?"
        )

    top_score = candidates[0]["score"]
    if top_score < config.SCHEMA_SIM_THRESHOLD:
        return (
            RetrievedSchema(tables=[], similarity_scores={}),
            True,
            f"Query terms did not match any tables with sufficient confidence (best score: {top_score:.2f}). "
            f"Please try rephrasing your question."
        )

    retrieved_table_names = [c["table_name"] for c in candidates]
    similarity_scores = {c["table_name"]: c["score"] for c in candidates}

    logger.info(f"[Layer 2] Retrieved tables: {retrieved_table_names} (top score: {top_score:.3f})")

    # ── Add bridge tables for reachability ───────────────────────────────────
    retrieved_table_names = _add_bridge_tables(retrieved_table_names)

    # ── Enrich with full column metadata ────────────────────────────────────
    full_schema = get_cached_schema()
    enriched_tables = []

    for table_name in retrieved_table_names:
        if table_name not in full_schema:
            logger.warning(f"[Layer 2] Table '{table_name}' in retrieved set but not in schema cache. Skipping.")
            continue

        table_data = full_schema[table_name]
        enriched_tables.append({
            "table_name":  table_name,
            "description": table_data["description"],
            "columns":     table_data["columns"],
        })

    retrieved_schema = RetrievedSchema(
        tables=enriched_tables,
        similarity_scores=similarity_scores,
    )

    return retrieved_schema, False, None


def _add_bridge_tables(table_names: list[str]) -> list[str]:
    """
    Checks if the retrieved tables are all connected via FK paths.
    Adds the minimum necessary bridge/junction tables if gaps exist.

    Example: if 'orders' and 'products' are retrieved, 'order_items'
    is the bridge and gets added automatically even if not in top-K results.
    """
    if len(table_names) <= 1:
        return table_names

    result = list(table_names)
    checked_pairs: set[frozenset] = set()

    for i, t1 in enumerate(table_names):
        for t2 in table_names[i + 1:]:
            pair = frozenset([t1, t2])
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)

            # Check if t1 and t2 are directly connected
            if not _directly_connected(t1, t2):
                # Try to find a 1-hop bridge
                bridge = _find_bridge_table(t1, t2)
                if bridge and bridge not in result:
                    logger.info(f"[Layer 2] Added bridge table '{bridge}' between '{t1}' and '{t2}'")
                    result.append(bridge)

    return result


def _directly_connected(t1: str, t2: str) -> bool:
    """Returns True if there is a direct FK edge between t1 and t2."""
    neighbors = [n["table"] for n in _graph.get(t1, [])]
    return t2 in neighbors


def _find_bridge_table(t1: str, t2: str) -> str | None:
    """
    Looks for a table that has direct FK edges to both t1 and t2.
    Returns the first bridge table found, or None.
    """
    t1_neighbors = {n["table"] for n in _graph.get(t1, [])}
    t2_neighbors = {n["table"] for n in _graph.get(t2, [])}
    bridges = t1_neighbors.intersection(t2_neighbors)
    return next(iter(bridges), None)


def format_schema_for_prompt(schema: RetrievedSchema) -> str:
    """
    Formats the retrieved schema into a clean string block for the LLM prompt.
    Shows table name, description, and column details (type, PK/FK, description).
    """
    lines = ["## Relevant Database Schema (only these tables exist — do not use others):"]

    for table in schema.tables:
        lines.append(f"\n### Table: {table['table_name']}")
        lines.append(f"Description: {table['description']}")
        lines.append("Columns:")

        for col in table["columns"]:
            flags = []
            if col.get("is_pk"):
                flags.append("PRIMARY KEY")
            if col.get("is_fk"):
                flags.append(f"FK → {col['references_table']}.{col['references_column']}")

            flag_str = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  - {col['name']} ({col['type']}){flag_str}: {col.get('description', '')}"
            )

    return "\n".join(lines)