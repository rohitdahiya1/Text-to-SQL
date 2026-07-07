"""
routers/chat.py

Main /chat POST endpoint.
Orchestrates the full 6-layer Text-to-SQL pipeline with:
  - Multi-turn conversation context
  - Clarification loop (asks user before generating if confidence is low)
  - Auto-correction loop (up to MAX_CORRECTION_RETRIES on validation failure)
  - Execution-level error retry
  - Structured trace logging per request
"""

from __future__ import annotations
import logging

from fastapi import APIRouter, HTTPException

from models.schemas import ChatRequest, ChatResponse
from chat.session import append_turn, get_lm_context, get_history
from glossary.terms import resolve_terms
from observability.logger import new_trace, record_layer, finalize_trace, LayerTimer

# Pipeline layers
from pipeline.query_understanding import extract_ir
from pipeline.schema_retrieval    import retrieve_relevant_schema
from pipeline.join_resolver       import resolve_join_paths
from pipeline.sql_generator       import generate_sql
from pipeline.validator           import validate_sql, build_correction_context
from pipeline.executor            import execute_sql, build_execution_error_context

import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Main conversational Text-to-SQL endpoint.

    Accepts a natural language message and a session_id,
    runs the full pipeline, and returns SQL + query results.
    """
    trace = new_trace(request.session_id, request.message)
    trace_id = trace["trace_id"]

    try:
        response = await _run_pipeline(request, trace)
        return response

    except Exception as e:
        logger.exception(f"[{trace_id}] Unhandled pipeline error: {e}")
        finalize_trace(trace, status="error", error=str(e))
        raise HTTPException(status_code=500, detail=f"Internal pipeline error: {str(e)}")


async def _run_pipeline(request: ChatRequest, trace: dict) -> ChatResponse:
    """
    Full pipeline execution. Returns a ChatResponse.
    Separated from the route handler for clean error propagation.
    """
    trace_id   = trace["trace_id"]
    session_id = request.session_id
    message    = request.message

    # Load conversation history for multi-turn context
    lm_context = get_lm_context(session_id)

    # ── Layer 1: Query Understanding ─────────────────────────────────────────
    with LayerTimer() as t1:
        ir, needs_clarification, clarification_question = extract_ir(message, lm_context)

    record_layer(trace, "layer_1_ir", {
        "intent":       ir.intent,
        "entities":     ir.entities,
        "operations":   ir.operations,
        "ambiguities":  ir.ambiguities,
        "confidence":   ir.confidence,
    }, t1.elapsed_ms)

    if needs_clarification:
        # Save the clarification turn so the follow-up has context
        append_turn(session_id, message, clarification_question, sql=None)
        finalize_trace(trace, status="clarification")

        return ChatResponse(
            session_id=session_id,
            message=message,
            sql=None,
            results=None,
            row_count=None,
            assumptions=[],
            reasoning=None,
            needs_clarification=True,
            clarification_question=clarification_question,
            trace_id=trace_id,
            latency_ms=trace["latency_ms"],
        )

    # ── Glossary resolution ───────────────────────────────────────────────────
    resolved_entities = resolve_terms(ir.entities)

    # ── Layer 2: Schema Retrieval ─────────────────────────────────────────────
    with LayerTimer() as t2:
        schema, retrieval_failed, retrieval_reason = retrieve_relevant_schema(ir, resolved_entities)

    record_layer(trace, "layer_2_schema", {
        "tables_retrieved": [t["table_name"] for t in schema.tables],
        "similarity_scores": schema.similarity_scores,
        "retrieval_failed":  retrieval_failed,
    }, t2.elapsed_ms)

    if retrieval_failed:
        append_turn(session_id, message, retrieval_reason, sql=None)
        finalize_trace(trace, status="error", error=retrieval_reason)
        return ChatResponse(
            session_id=session_id,
            message=message,
            sql=None,
            results=None,
            row_count=None,
            assumptions=[],
            reasoning=None,
            needs_clarification=True,
            clarification_question=retrieval_reason,
            trace_id=trace_id,
            latency_ms=trace["latency_ms"],
        )

    # ── Layer 3: Join Resolution ──────────────────────────────────────────────
    with LayerTimer() as t3:
        join_result = resolve_join_paths(schema)

    record_layer(trace, "layer_3_joins", {
        "join_count":       len(join_result.join_fragments),
        "ambiguous_count":  len(join_result.ambiguous_paths),
        "unreachable_count": len(join_result.unreachable_pairs),
        "join_paths":       [f"{j.from_table} → {j.to_table}" for j in join_result.join_fragments],
    }, t3.elapsed_ms)

    # ── Layers 4+5: Generate → Validate → Correct Loop ───────────────────────
    generated_sql   = None
    validation_result = None
    correction_context: str | None = None
    attempt = 0

    while attempt < config.MAX_CORRECTION_RETRIES:
        attempt += 1
        logger.info(f"[{trace_id}] SQL generation attempt {attempt}/{config.MAX_CORRECTION_RETRIES}")

        # Layer 4: SQL Generation
        with LayerTimer() as t4:
            gen = generate_sql(
                user_query=message,
                ir=ir,
                resolved_entities=resolved_entities,
                schema=schema,
                join_result=join_result,
                conversation_history=lm_context,
                correction_context=correction_context,
            )

        record_layer(trace, f"layer_4_sql_attempt_{attempt}", {
            "sql":         gen.sql,
            "reasoning":   gen.reasoning,
            "assumptions": gen.assumptions,
            "confidence":  gen.confidence,
        }, t4.elapsed_ms)

        if not gen.sql:
            correction_context = "SQL generation returned empty. Please generate a complete SQL query."
            continue

        # Layer 5: Validation
        with LayerTimer() as t5:
            validation_result = validate_sql(gen.sql, schema, join_result)

        record_layer(trace, f"layer_5_validation_attempt_{attempt}", {
            "is_valid":       validation_result.is_valid,
            "errors":         validation_result.errors,
            "security_flags": validation_result.security_flags,
        }, t5.elapsed_ms)

        if validation_result.security_flags:
            # Hard stop — do not retry security violations
            error_msg = "Query blocked: contains forbidden SQL operations."
            finalize_trace(trace, status="error", error=error_msg)
            return _error_response(session_id, message, error_msg, trace_id, trace["latency_ms"])

        if validation_result.is_valid:
            generated_sql = gen
            break

        # Build structured correction context for next attempt
        correction_context = build_correction_context(gen.sql, validation_result, schema)
        logger.warning(f"[{trace_id}] Validation failed (attempt {attempt}). Retrying with correction context.")

    # If all retries exhausted and still invalid
    if generated_sql is None or (validation_result and not validation_result.is_valid):
        errors = validation_result.errors if validation_result else ["SQL generation failed."]
        error_msg = (
            f"Could not generate a valid SQL query after {config.MAX_CORRECTION_RETRIES} attempts. "
            f"Last errors: {'; '.join(errors)}. "
            f"Please try rephrasing your question."
        )
        append_turn(session_id, message, error_msg, sql=None)
        finalize_trace(trace, status="error", error=error_msg)
        return _error_response(session_id, message, error_msg, trace_id, trace["latency_ms"])

    # ── Layer 6: Execution ────────────────────────────────────────────────────
    with LayerTimer() as t6:
        exec_result = execute_sql(generated_sql.sql)

    record_layer(trace, "layer_6_execution", {
        "success":       exec_result.success,
        "row_count":     exec_result.row_count,
        "is_empty":      exec_result.is_empty,
        "error_message": exec_result.error_message,
    }, t6.elapsed_ms)

    # Handle DB-level execution errors — one retry with execution error context
    if not exec_result.success:
        exec_error_ctx = build_execution_error_context(exec_result.error_message, generated_sql.sql)
        logger.warning(f"[{trace_id}] Execution failed. Attempting one SQL correction.")

        with LayerTimer() as t4_retry:
            gen_retry = generate_sql(
                user_query=message,
                ir=ir,
                resolved_entities=resolved_entities,
                schema=schema,
                join_result=join_result,
                conversation_history=lm_context,
                correction_context=exec_error_ctx,
            )

        record_layer(trace, "layer_4_sql_exec_retry", {
            "sql": gen_retry.sql
        }, t4_retry.elapsed_ms)

        val_retry = validate_sql(gen_retry.sql, schema, join_result)
        if val_retry.is_valid:
            with LayerTimer() as t6_retry:
                exec_result = execute_sql(gen_retry.sql)
            record_layer(trace, "layer_6_execution_retry", {
                "success":   exec_result.success,
                "row_count": exec_result.row_count,
            }, t6_retry.elapsed_ms)
            generated_sql = gen_retry

        if not exec_result.success:
            error_msg = f"Query execution failed: {exec_result.error_message}"
            append_turn(session_id, message, error_msg, sql=generated_sql.sql)
            finalize_trace(trace, status="error", error=error_msg, final_sql=generated_sql.sql)
            return _error_response(session_id, message, error_msg, trace_id, trace["latency_ms"])

    # ── Build assistant response message ─────────────────────────────────────
    if exec_result.is_empty:
        assistant_message = exec_result.diagnostic or "Query executed successfully but returned no results."
    else:
        assistant_message = (
            f"Query returned {exec_result.row_count} row(s)."
            + (f" Note: {'; '.join(generated_sql.assumptions)}" if generated_sql.assumptions else "")
        )

    # ── Save turn to session ──────────────────────────────────────────────────
    append_turn(session_id, message, assistant_message, sql=generated_sql.sql)

    finalize_trace(
        trace,
        status="success",
        final_sql=generated_sql.sql,
    )

    return ChatResponse(
        session_id=session_id,
        message=message,
        sql=generated_sql.sql,
        results=exec_result.rows,
        row_count=exec_result.row_count,
        assumptions=generated_sql.assumptions,
        reasoning=generated_sql.reasoning,
        needs_clarification=False,
        clarification_question=None,
        error=exec_result.diagnostic if exec_result.is_empty else None,
        trace_id=trace_id,
        latency_ms=trace["latency_ms"],
    )


def _error_response(
    session_id: str,
    message: str,
    error: str,
    trace_id: str,
    latency_ms: dict,
) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message=message,
        sql=None,
        results=None,
        row_count=None,
        assumptions=[],
        reasoning=None,
        needs_clarification=False,
        clarification_question=None,
        error=error,
        trace_id=trace_id,
        latency_ms=latency_ms,
    )