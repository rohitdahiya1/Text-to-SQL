"""
observability/logger.py

Structured trace logging for the Text-to-SQL pipeline.
Each query gets a unique trace_id. Every layer records its output and latency.

The trace log is a dict that accumulates as the request flows through layers.
At the end, it's logged as a single structured JSON line — easy to ship to
any log aggregator (Datadog, CloudWatch, Grafana Loki, etc.).

Usage pattern:
    trace = new_trace(session_id, user_message)
    trace = record_layer(trace, "layer_1_ir", ir.dict(), latency_ms=45)
    ...
    finalize_trace(trace)
"""

from __future__ import annotations
import json
import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("text_to_sql.trace")


def new_trace(session_id: str, user_message: str) -> dict:
    """
    Creates a new trace dict for a single request.
    """
    return {
        "trace_id":    str(uuid.uuid4()),
        "session_id":  session_id,
        "user_message": user_message,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "layers":      {},
        "latency_ms":  {},
        "status":      "in_progress",
        "_start_time": time.perf_counter(),
    }


def record_layer(
    trace: dict,
    layer_name: str,
    data: dict,
    latency_ms: float,
) -> dict:
    """
    Records the output and latency of a pipeline layer into the trace.

    Args:
        trace: The current trace dict.
        layer_name: e.g. "layer_1_ir", "layer_2_schema", "layer_4_sql"
        data: The layer's output as a dict (serializable).
        latency_ms: Time taken for this layer in milliseconds.

    Returns:
        Updated trace dict.
    """
    trace["layers"][layer_name]      = data
    trace["latency_ms"][layer_name]  = round(latency_ms, 2)
    return trace


def finalize_trace(
    trace: dict,
    status: str,           # "success" | "clarification" | "error"
    final_sql: str | None  = None,
    error: str | None      = None,
) -> dict:
    """
    Finalises and emits the trace as a single structured log line.

    Args:
        trace: The accumulated trace dict.
        status: Final status of the request.
        final_sql: The SQL that was actually executed (if any).
        error: Error message if status == "error".

    Returns:
        The finalised trace dict (also logged).
    """
    elapsed = (time.perf_counter() - trace.pop("_start_time", 0)) * 1000
    trace["status"]          = status
    trace["total_latency_ms"] = round(elapsed, 2)
    trace["final_sql"]       = final_sql
    trace["error"]           = error

    # Remove internal keys before logging
    loggable = {k: v for k, v in trace.items() if not k.startswith("_")}

    logger.info(json.dumps(loggable, default=str))
    return trace


class LayerTimer:
    """
    Context manager for timing a pipeline layer.

    Usage:
        with LayerTimer() as t:
            result = do_something()
        latency = t.elapsed_ms
    """
    def __init__(self):
        self.elapsed_ms: float = 0.0
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000