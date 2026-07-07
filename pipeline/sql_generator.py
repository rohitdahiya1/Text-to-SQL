"""
pipeline/sql_generator.py  —  Layer 4

Generates SQL using the LLM given:
  - The structured IR from Layer 1
  - The trimmed schema context from Layer 2
  - The pre-resolved join paths from Layer 3
  - Conversation history for multi-turn context

The LLM's job here is narrow and well-constrained:
  - Write SELECT, WHERE, GROUP BY, ORDER BY, LIMIT clauses
  - Use ONLY the tables and columns provided in the schema block
  - Use ONLY the join conditions provided in the join block
  - Record any assumptions it had to make

For complex queries (subqueries, CTEs, window functions), uses
a two-step plan-then-generate approach for higher accuracy.
"""

from __future__ import annotations
import json
import logging

from openai import AzureOpenAI
import config
from models.schemas import (
    GeneratedSQL,
    IntermediateRepresentation,
    RetrievedSchema,
    JoinResolutionResult,
)
from pipeline.query_understanding import format_ir_for_prompt
from pipeline.schema_retrieval import format_schema_for_prompt
from pipeline.join_resolver import get_join_prompt_block

logger = logging.getLogger(__name__)

_client = AzureOpenAI(
    api_key=config.AZURE_OPENAI_API_KEY,
    azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
    api_version=config.AZURE_OPENAI_API_VERSION,
)

_SYSTEM_PROMPT = """
You are a precise SQL generation engine for a PostgreSQL (Supabase) e-commerce database.

STRICT RULES — violating any of these makes your output incorrect:
1. Use ONLY the tables listed in the "Relevant Database Schema" section. Never invent table names.
2. Use ONLY the column names listed for each table. Never invent column names.
3. Use ONLY the join conditions from the "Pre-resolved Join Paths" section. Do not modify join keys.
4. Generate standard PostgreSQL SQL only. No proprietary syntax.
5. Always use table aliases in multi-table queries to avoid ambiguity.
6. Do not use SELECT *. Always list specific columns.
7. Apply LIMIT {max_rows} unless the user explicitly asks for all rows or an aggregation.
8. For date filtering, use the resolved ISO dates provided — do not re-interpret date language.
9. If a query requires a subquery or CTE, use it — correctness over simplicity.

You must respond ONLY with a valid JSON object:
{{
  "sql": "<the complete SQL query>",
  "reasoning": "<2-3 sentence explanation of how you built this query>",
  "assumptions": ["<any ambiguity you resolved with an assumption>"],
  "confidence": <float 0.0-1.0>
}}

No markdown, no explanation outside the JSON, no code fences.
""".strip()

_COMPLEX_PLAN_SYSTEM_PROMPT = """
You are a SQL query planner. Given a user question and schema context, produce a
step-by-step plain-English plan for how to write the SQL.
Be specific: name the tables, filters, aggregations, and ordering you would use.
Do NOT write SQL yet.

Respond only with a numbered list of steps. No JSON.
""".strip()


# Operations that signal a complex query needing two-step generation
_COMPLEX_OPERATIONS = {
    "window function", "rank", "dense_rank", "row_number",
    "cte", "with clause", "subquery", "nested", "percentile",
    "running total", "cumulative", "pivot", "self-join"
}


def generate_sql(
    user_query: str,
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
    conversation_history: list[dict],
    correction_context: str | None = None,
) -> GeneratedSQL:
    """
    Generates SQL for the user query.

    Args:
        user_query: Original user question.
        ir: Structured IR from Layer 1.
        resolved_entities: Entities with glossary mappings.
        schema: Retrieved schema from Layer 2.
        join_result: Resolved join paths from Layer 3.
        conversation_history: Last N conversation turns.
        correction_context: If this is a retry, the structured error message from Layer 5.

    Returns:
        GeneratedSQL with sql, reasoning, assumptions, and confidence.
    """
    is_complex = _is_complex_query(ir)

    if is_complex and correction_context is None:
        # Two-step: plan first, then generate
        logger.info("[Layer 4] Complex query detected. Using two-step plan → generate.")
        plan = _generate_plan(user_query, ir, resolved_entities, schema, join_result, conversation_history)
        logger.debug(f"[Layer 4] Query plan:\n{plan}")
        return _generate_from_plan(user_query, plan, ir, resolved_entities, schema, join_result, conversation_history)
    else:
        # Single-step generation (also used for correction retries)
        return _generate_single_shot(user_query, ir, resolved_entities, schema, join_result, conversation_history, correction_context)


def _is_complex_query(ir: IntermediateRepresentation) -> bool:
    """Detects if a query likely needs CTEs or window functions."""
    ops_lower = {op.lower() for op in ir.operations}
    return bool(ops_lower.intersection(_COMPLEX_OPERATIONS)) or ir.intent in ("ranking", "comparison")


def _build_context_block(
    user_query: str,
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
) -> str:
    """Assembles the full context block injected into the LLM prompt."""
    parts = [
        f"## User Question\n{user_query}",
        "",
        format_ir_for_prompt(ir, resolved_entities),
        "",
        format_schema_for_prompt(schema),
        "",
        get_join_prompt_block(join_result),
    ]
    return "\n".join(parts)


def _generate_single_shot(
    user_query: str,
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
    conversation_history: list[dict],
    correction_context: str | None,
) -> GeneratedSQL:
    """Single-shot SQL generation (used for simple queries and correction retries)."""

    system_prompt = _SYSTEM_PROMPT.format(max_rows=config.MAX_RESULT_ROWS)
    context_block = _build_context_block(user_query, ir, resolved_entities, schema, join_result)

    user_content = context_block
    if correction_context:
        user_content += f"\n\n## ⚠️ Previous SQL had errors. Fix these specific issues:\n{correction_context}"

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})

    logger.debug("[Layer 4] Sending SQL generation request to LLM.")

    response = _client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=1500,
    )

    raw_json = response.choices[0].message.content.strip()
    logger.debug(f"[Layer 4] Raw SQL response: {raw_json[:300]}...")

    return _parse_sql_response(raw_json)


def _generate_plan(
    user_query: str,
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
    conversation_history: list[dict],
) -> str:
    """Step 1 of two-step: generate a plain-English query plan."""
    context_block = _build_context_block(user_query, ir, resolved_entities, schema, join_result)

    messages = [{"role": "system", "content": _COMPLEX_PLAN_SYSTEM_PROMPT}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": context_block})

    response = _client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=0.0,
        max_tokens=600,
    )

    return response.choices[0].message.content.strip()


def _generate_from_plan(
    user_query: str,
    plan: str,
    ir: IntermediateRepresentation,
    resolved_entities: list[dict],
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
    conversation_history: list[dict],
) -> GeneratedSQL:
    """Step 2 of two-step: generate SQL from the plan."""
    system_prompt = _SYSTEM_PROMPT.format(max_rows=config.MAX_RESULT_ROWS)
    context_block = _build_context_block(user_query, ir, resolved_entities, schema, join_result)

    user_content = (
        f"{context_block}\n\n"
        f"## Query Plan (follow this step by step):\n{plan}\n\n"
        f"Now generate the complete SQL following this plan exactly."
    )

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})

    response = _client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
        max_tokens=1500,
    )

    raw_json = response.choices[0].message.content.strip()
    return _parse_sql_response(raw_json)


def _parse_sql_response(raw_json: str) -> GeneratedSQL:
    """Parses the LLM JSON response into a GeneratedSQL object."""
    try:
        data = json.loads(raw_json)
        return GeneratedSQL(
            sql=data.get("sql", "").strip(),
            reasoning=data.get("reasoning", ""),
            assumptions=data.get("assumptions", []),
            confidence=float(data.get("confidence", 0.5)),
        )
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"[Layer 4] Failed to parse SQL response: {e}. Raw: {raw_json[:300]}")
        return GeneratedSQL(
            sql="",
            reasoning="Failed to parse LLM response.",
            assumptions=["Response parsing failed."],
            confidence=0.0,
        )