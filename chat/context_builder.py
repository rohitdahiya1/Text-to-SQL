"""
chat/context_builder.py

Assembles conversation history into a clean, token-efficient context block
for injection into LLM prompts (Layers 1 and 4).

Why this is a separate file from session.py:
  - session.py owns storage (read/write turns)
  - context_builder.py owns formatting (how history is presented to the LLM)
  - These two concerns change independently: you might change storage to Supabase
    without changing how context is formatted, or vice versa.

Multi-turn handling strategy:
  - We include the last N turns (config.CONVERSATION_HISTORY_TURNS)
  - Each turn includes the user message + assistant response
  - If the assistant generated SQL in a prior turn, we include a summary of it
    so the LLM understands what was previously queried (helps with "now filter by X" follow-ups)
  - We deliberately exclude raw result data from context (too many tokens)
    and instead include only the row count and any assumptions from prior turns
"""

from __future__ import annotations
import logging
from chat.session import get_history
import config

logger = logging.getLogger(__name__)


def build_lm_context(session_id: str) -> list[dict]:
    """
    Builds the OpenAI-format message list representing recent conversation history.
    Used by both Layer 1 (query understanding) and Layer 4 (SQL generation).

    Returns a list of {"role": "user"|"assistant", "content": "..."} dicts
    representing the last N turns, ready to be inserted before the current
    user message in the LLM prompt.

    The assistant content is enriched with SQL context (not just the natural
    language response) so the LLM can reference what was queried before.

    Example output:
        [
            {"role": "user",      "content": "Show me top 5 customers by revenue"},
            {"role": "assistant", "content": "Returned 5 rows. SQL used: SELECT c.full_name, ..."},
            {"role": "user",      "content": "Now filter by Mumbai only"},
            {"role": "assistant", "content": "Returned 2 rows. SQL used: SELECT c.full_name, ..."},
        ]
    """
    history = get_history(session_id)

    if not history:
        return []

    # Take only the last N turns
    recent = history[-config.CONVERSATION_HISTORY_TURNS:]

    messages: list[dict] = []

    for turn in recent:
        # User side — include the original question as-is
        messages.append({
            "role":    "user",
            "content": turn["user"],
        })

        # Assistant side — include the response AND a compact SQL reference
        assistant_content = _format_assistant_turn(turn)
        messages.append({
            "role":    "assistant",
            "content": assistant_content,
        })

    logger.debug(f"[ContextBuilder] Built {len(messages)} messages from {len(recent)} turns for session '{session_id}'.")
    return messages


def _format_assistant_turn(turn: dict) -> str:
    """
    Formats a single assistant turn into a compact content string.

    Includes:
      - The assistant's natural language response
      - The SQL that was generated (if any), truncated to avoid token bloat
        but long enough to be useful for follow-up query context

    The SQL is shown in a compact format so the LLM knows:
      - Which tables were used
      - What filters/aggregations were applied
      - What it can build on for a follow-up query
    """
    parts = [turn["assistant"]]

    if turn.get("sql"):
        # Include the SQL but truncate very long queries to save tokens
        sql = turn["sql"].strip()
        if len(sql) > 600:
            sql = sql[:600] + "\n-- [truncated for context]"
        parts.append(f"[Previous SQL: {sql}]")

    return "\n".join(parts)


def build_system_context_note(session_id: str) -> str:
    """
    Builds a brief note about the conversation context for injection into
    the system prompt, so the LLM is aware this is a multi-turn session.

    Returns an empty string if this is the first turn (no history).
    """
    history = get_history(session_id)
    if not history:
        return ""

    turn_count = len(history)
    last_query = history[-1]["user"] if history else ""

    return (
        f"\nNote: This is turn {turn_count + 1} of an ongoing conversation. "
        f"The user's previous question was: \"{last_query[:100]}\". "
        f"If the current question is a follow-up (e.g. 'now filter by X', 'show only Y'), "
        f"use the previous SQL context to build on, not start from scratch."
    )


def get_prior_sql(session_id: str) -> str | None:
    """
    Returns the SQL from the most recent successful turn, or None.
    Useful for understanding what the user might be refining.
    """
    history = get_history(session_id)
    for turn in reversed(history):
        if turn.get("sql"):
            return turn["sql"]
    return None