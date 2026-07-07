"""
models/schemas.py
Pydantic models for API requests/responses and internal pipeline data structures.
"""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── API Layer ────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique conversation session identifier")
    message: str    = Field(..., description="Natural language query from the user")


class ChatResponse(BaseModel):
    session_id:    str
    message:       str                    # original user message echo
    sql:           Optional[str]          # generated SQL (None if clarification needed)
    results:       Optional[list[dict]]   # query results as list of row dicts
    row_count:     Optional[int]
    assumptions:   list[str]             # LLM assumptions made during generation
    reasoning:     Optional[str]         # LLM's chain-of-thought summary
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    error:         Optional[str] = None  # user-facing error if pipeline failed
    trace_id:      str  = ""
    latency_ms:    dict = Field(default_factory=dict)  # per-layer latency breakdown


class SessionHistoryResponse(BaseModel):
    session_id: str
    turns: list[dict]


# ── Internal Pipeline Models ──────────────────────────────────────────────────

class IntermediateRepresentation(BaseModel):
    """Output of Layer 1: query_understanding.py"""
    intent:       str                    # select | aggregation | ranking | comparison | filter
    entities:     list[str]             # key nouns extracted (products, customers, revenue…)
    operations:   list[str]             # SQL-level ops implied (GROUP BY, ORDER BY, SUM…)
    temporal_refs: list[dict]           # [{"raw": "last month", "resolved": {"start":…,"end":…}}]
    filters:      list[dict]            # explicit filter hints [{"column_hint":"status","value":"delivered"}]
    ambiguities:  list[str]             # things that could be interpreted multiple ways
    confidence:   float                 # 0.0–1.0; below IR_CONFIDENCE_THRESHOLD → ask user


class RetrievedSchema(BaseModel):
    """Output of Layer 2: schema_retrieval.py"""
    tables: list[dict]   # each: {table_name, description, columns:[{name,type,description,is_pk,is_fk,references}]}
    similarity_scores: dict[str, float]  # table_name → cosine sim score


class JoinPath(BaseModel):
    """A single resolved join path between two tables"""
    from_table: str
    to_table:   str
    join_sql:   str      # e.g. "orders JOIN customers ON orders.customer_id = customers.customer_id"
    path:       list[str]  # intermediate tables in the path


class JoinResolutionResult(BaseModel):
    """Output of Layer 3: join_resolver.py"""
    join_fragments:    list[JoinPath]
    ambiguous_paths:   list[dict]    # paths where multiple valid routes exist
    unreachable_pairs: list[dict]    # table pairs with no FK path


class GeneratedSQL(BaseModel):
    """Output of Layer 4: sql_generator.py"""
    sql:         str
    reasoning:   str
    assumptions: list[str]
    confidence:  float


class ValidationResult(BaseModel):
    """Output of Layer 5: validator.py"""
    is_valid:       bool
    errors:         list[str]           # structured error messages
    security_flags: list[str]           # any DML/DROP/TRUNCATE detected
    corrected_sql:  Optional[str] = None


class ExecutionResult(BaseModel):
    """Output of Layer 6: executor.py"""
    success:       bool
    rows:          list[dict]
    row_count:     int
    error_message: Optional[str] = None
    is_empty:      bool = False
    diagnostic:    Optional[str] = None  # human-readable reason for empty result