"""
pipeline/join_resolver.py  —  Layer 3

Extracts the set of tables from the retrieved schema and resolves
the correct join paths between them using the schema graph (BFS).

This layer is fully deterministic — no LLM involved.
Its output is injected directly into the SQL generation prompt,
so the LLM never has to guess join keys or join order.
"""

from __future__ import annotations
import logging

from models.schemas import RetrievedSchema, JoinResolutionResult
from schema.graph import resolve_joins, format_joins_for_prompt

logger = logging.getLogger(__name__)


def resolve_join_paths(schema: RetrievedSchema) -> JoinResolutionResult:
    """
    Takes the retrieved schema (list of relevant tables) and resolves
    the FK join paths connecting them.

    Args:
        schema: RetrievedSchema from Layer 2.

    Returns:
        JoinResolutionResult with pre-validated join SQL fragments.
    """
    table_names = [t["table_name"] for t in schema.tables]

    if not table_names:
        return JoinResolutionResult(
            join_fragments=[],
            ambiguous_paths=[],
            unreachable_pairs=[],
        )

    logger.debug(f"[Layer 3] Resolving joins for tables: {table_names}")
    result = resolve_joins(table_names)

    if result.unreachable_pairs:
        logger.warning(f"[Layer 3] Unreachable table pairs: {result.unreachable_pairs}")

    if result.ambiguous_paths:
        logger.info(f"[Layer 3] Ambiguous join paths detected: {len(result.ambiguous_paths)}")

    logger.info(
        f"[Layer 3] Resolved {len(result.join_fragments)} join paths. "
        f"Ambiguous: {len(result.ambiguous_paths)}. Unreachable: {len(result.unreachable_pairs)}."
    )

    return result


def get_join_prompt_block(result: JoinResolutionResult) -> str:
    """Convenience wrapper to get formatted join block for LLM prompt."""
    return format_joins_for_prompt(result)