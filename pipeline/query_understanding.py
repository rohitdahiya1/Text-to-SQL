"""
pipeline/query_understanding.py  —  Layer 1

Transforms the raw user natural language query into a structured
Intermediate Representation (IR) using a single LLM call.

The IR captures:
  - intent (what kind of SQL operation is needed)
  - entities (key nouns to search schema with)
  - operations (SQL-level hints: GROUP BY, ORDER BY, etc.)
  - temporal_refs (date/time expressions, resolved to ranges)
  - filters (explicit filter hints the user stated)
  - ambiguities (things that could mean multiple different things)
  - confidence (0–1; low → ask user to clarify before proceeding)

Conversation history (last N turns) is included so multi-turn
follow-up queries like "now filter by Delhi only" are handled correctly.
"""

from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from openai import AzureOpenAI

import config
from models.schemas import IntermediateRepresentation

logger = logging.getLogger(__name__)

_client = AzureOpenAI(
    api_key=config.AZURE_OPENAI_API_KEY,
    azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
    api_version=config.AZURE_OPENAI_API_VERSION,
)

_SYSTEM_PROMPT = """
You are a query understanding engine for an e-commerce analytics system.
Your job is to analyze a user's natural language question and extract structured information.

The database is an e-commerce platform with these general areas:
- Customers and their addresses (with region/geography)
- Products, categories, and inventory/stock
- Orders, order items, and payments
- Reviews and ratings

Today's date: {today}

You must respond ONLY with a valid JSON object — no preamble, no markdown, no explanation.

JSON schema to follow exactly:
{{
  "intent": "<one of: select | aggregation | ranking | comparison | filter>",
  "entities": ["<key noun 1>", "<key noun 2>", ...],
  "operations": ["<SQL operation hint>", ...],
  "temporal_refs": [
    {{
      "raw": "<what the user said>",
      "resolved_start": "<ISO date or null>",
      "resolved_end":   "<ISO date or null>"
    }}
  ],
  "filters": [
    {{
      "column_hint": "<likely column or concept>",
      "value":       "<filter value>",
      "operator":    "<= | >= | = | IN | LIKE | BETWEEN>"
    }}
  ],
  "ambiguities": ["<description of anything unclear>"],
  "confidence": <float between 0.0 and 1.0>
}}

Rules:
- confidence < 0.7 means the query is ambiguous or unclear enough that you need clarification.
- For temporal_refs, resolve relative dates (e.g. "last month", "Q3 2024", "this year") to actual ISO 8601 date strings.
- Q1 = Jan-Mar, Q2 = Apr-Jun, Q3 = Jul-Sep, Q4 = Oct-Dec.
- entities should be the key business concepts (e.g. "revenue", "customers", "delivered orders").
- Do NOT write SQL. Only extract structured meaning.
""".strip()

_CLARIFICATION_NEEDED_TEMPLATE = """
Looking at your question "{query}", I need a bit more clarity before I can generate an accurate SQL query:

{questions}

Could you clarify the above so I can give you the most accurate results?
""".strip()


def extract_ir(
    user_query: str,
    conversation_history: list[dict],
) -> tuple[IntermediateRepresentation, bool, str | None]:
    """
    Extracts the Intermediate Representation from the user query.

    Args:
        user_query: The latest message from the user.
        conversation_history: List of past turns as {"role": "user"|"assistant", "content": "..."}
                              Pass the last N turns (controlled by config.CONVERSATION_HISTORY_TURNS).

    Returns:
        (ir, needs_clarification, clarification_question)
        - ir: the parsed IntermediateRepresentation
        - needs_clarification: True if confidence < threshold
        - clarification_question: A user-facing question string if needs_clarification is True
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system_prompt = _SYSTEM_PROMPT.format(today=today)

    # Build message list: system + history + current query
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_query})

    logger.debug(f"[Layer 1] Sending query to LLM for IR extraction: '{user_query[:80]}...'")

    response = _client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=messages,
        temperature=0.0,       # deterministic
        response_format={"type": "json_object"},
        max_tokens=800,
    )

    raw_json = response.choices[0].message.content.strip()
    logger.debug(f"[Layer 1] Raw IR response: {raw_json}")

    try:
        ir_dict = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error(f"[Layer 1] Failed to parse IR JSON: {e}. Raw: {raw_json}")
        # Fallback IR with low confidence to trigger clarification
        ir_dict = {
            "intent": "select",
            "entities": [],
            "operations": [],
            "temporal_refs": [],
            "filters": [],
            "ambiguities": ["Could not parse query structure."],
            "confidence": 0.0,
        }

    ir = IntermediateRepresentation(**ir_dict)

    # ── Confidence check ──────────────────────────────────────────────────────
    if ir.confidence < config.IR_CONFIDENCE_THRESHOLD:
        clarification_q = _build_clarification_question(user_query, ir)
        logger.info(f"[Layer 1] Low confidence ({ir.confidence:.2f}). Requesting clarification.")
        return ir, True, clarification_q

    return ir, False, None


def _build_clarification_question(query: str, ir: IntermediateRepresentation) -> str:
    """
    Builds a user-friendly clarification question based on detected ambiguities.
    """
    questions = []

    for i, ambiguity in enumerate(ir.ambiguities, 1):
        questions.append(f"{i}. {ambiguity}")

    if not questions:
        questions.append("1. Could you rephrase your question with more specific details?")

    return _CLARIFICATION_NEEDED_TEMPLATE.format(
        query=query,
        questions="\n".join(questions),
    )


def format_ir_for_prompt(ir: IntermediateRepresentation, resolved_entities: list[dict]) -> str:
    """
    Formats the IR into a string block for injection into the SQL generation prompt.
    Includes resolved glossary mappings alongside raw entities.
    """
    lines = [
        f"## Query Understanding",
        f"Intent: {ir.intent}",
        f"Operations implied: {', '.join(ir.operations) if ir.operations else 'none'}",
        "",
        "## Entities (with glossary resolution):",
    ]

    for entity in resolved_entities:
        if entity["resolved"]:
            lines.append(
                f"  - '{entity['original']}' → table: {entity.get('table','?')}, "
                f"column: {entity.get('column','(see table)')}. Note: {entity.get('notes','')}"
            )
        else:
            lines.append(f"  - '{entity['original']}' (no glossary match — infer from schema)")

    if ir.temporal_refs:
        lines.append("\n## Temporal References (already resolved to dates):")
        for tr in ir.temporal_refs:
            lines.append(
                f"  - '{tr['raw']}' → start: {tr.get('resolved_start','?')}, end: {tr.get('resolved_end','?')}"
            )

    if ir.filters:
        lines.append("\n## Explicit Filters from user query:")
        for f in ir.filters:
            lines.append(f"  - {f.get('column_hint','?')} {f.get('operator','=')} '{f.get('value','?')}'")

    if ir.ambiguities:
        lines.append("\n## Assumptions made (log these in your response):")
        for a in ir.ambiguities:
            lines.append(f"  - {a}")

    return "\n".join(lines)