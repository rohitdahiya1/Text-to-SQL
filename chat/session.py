"""
chat/session.py

In-memory session store for multi-turn conversation history.
Each session is keyed by a session_id string.

Design decisions:
  - In-memory dict: appropriate for internal tool (single server process).
  - Stores full turns (user message + assistant response + generated SQL).
  - get_history() trims to the last N turns before returning for LLM context.
  - No persistence across server restarts (acceptable for internal use).

To upgrade to persistent sessions later: replace the dict with
Supabase table writes/reads using the same interface.
"""

from __future__ import annotations
import logging
from collections import defaultdict
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

# session_id → list of turn dicts
_sessions: dict[str, list[dict]] = defaultdict(list)


def append_turn(
    session_id: str,
    user_message: str,
    assistant_message: str,
    sql: str | None,
) -> None:
    """
    Appends a completed turn to the session history.

    Args:
        session_id: Unique identifier for the conversation session.
        user_message: The user's natural language query.
        assistant_message: The assistant's response (natural language summary).
        sql: The generated SQL (if any) for this turn.
    """
    turn = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "user":        user_message,
        "assistant":   assistant_message,
        "sql":         sql,
    }
    _sessions[session_id].append(turn)
    logger.debug(f"[Session] Turn appended to session '{session_id}'. Total turns: {len(_sessions[session_id])}")


def get_history(session_id: str) -> list[dict]:
    """Returns the full turn history for a session."""
    return list(_sessions.get(session_id, []))


def get_lm_context(session_id: str) -> list[dict]:
    """
    Returns the last N turns formatted as OpenAI-style message dicts
    ({"role": "user"|"assistant", "content": "..."}) for injection
    into LLM prompts.

    Only the last config.CONVERSATION_HISTORY_TURNS turns are included
    to keep token usage bounded while still supporting follow-up queries.
    """
    history = _sessions.get(session_id, [])
    recent_turns = history[-config.CONVERSATION_HISTORY_TURNS:]

    messages = []
    for turn in recent_turns:
        messages.append({"role": "user",      "content": turn["user"]})
        messages.append({"role": "assistant",  "content": turn["assistant"]})

    return messages


def clear_session(session_id: str) -> None:
    """Clears all turns for a given session."""
    if session_id in _sessions:
        del _sessions[session_id]
        logger.info(f"[Session] Session '{session_id}' cleared.")


def list_sessions() -> list[str]:
    """Returns all active session IDs."""
    return list(_sessions.keys())


def get_session_summary(session_id: str) -> dict:
    """Returns a summary dict of the session for the /sessions endpoint."""
    history = _sessions.get(session_id, [])
    return {
        "session_id":   session_id,
        "turn_count":   len(history),
        "started_at":   history[0]["timestamp"] if history else None,
        "last_turn_at": history[-1]["timestamp"] if history else None,
        "turns":        history,
    }