"""
routers/sessions.py

Endpoints for retrieving and managing conversation session history.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException
from models.schemas import SessionHistoryResponse
from chat.session import get_session_summary, list_sessions, clear_session

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str) -> SessionHistoryResponse:
    """Returns the full conversation history for a session."""
    summary = get_session_summary(session_id)
    if summary["turn_count"] == 0:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or has no history.")
    return SessionHistoryResponse(
        session_id=session_id,
        turns=summary["turns"],
    )


@router.get("", response_model=list[str])
async def list_all_sessions() -> list[str]:
    """Returns all active session IDs."""
    return list_sessions()


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Clears all history for a session."""
    clear_session(session_id)
    return {"deleted": True, "session_id": session_id}