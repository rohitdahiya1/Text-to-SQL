"""
pipeline/executor.py  —  Layer 6

Executes the validated SQL safely against Supabase (PostgreSQL).
Handles empty results, DB errors, row limits, and query timeouts.

Uses the Supabase Python client's rpc or raw SQL execution path.
All queries run as the service_role user but are restricted to
SELECT-only at the application level (security layer already rejected DML).

On DB-level error, returns a structured ExecutionResult with the error
message so the correction loop can feed it back to sql_generator.py.
"""

from __future__ import annotations
import logging
from supabase import create_client, Client

import config
from models.schemas import ExecutionResult

logger = logging.getLogger(__name__)


def _get_client() -> Client:
    return create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)


def execute_sql(sql: str) -> ExecutionResult:
    """
    Executes a validated SQL query against Supabase.

    Enforces:
      - Row limit via LIMIT injection if not already present
      - Query timeout via statement_timeout (set per-session)
      - Read-only mode (DML already blocked by validator, but belt-and-suspenders)

    Args:
        sql: The validated SQL query to execute.

    Returns:
        ExecutionResult with rows, row_count, or error details.
    """
    sql = _inject_limit_if_missing(sql)

    logger.debug(f"[Layer 6] Executing SQL:\n{sql}")

    client = _get_client()

    try:
        # Execute via Supabase RPC helper that wraps raw SQL.
        # Create this function once in Supabase SQL editor:
        #
        # CREATE OR REPLACE FUNCTION execute_readonly_query(query_text text)
        # RETURNS json AS $$
        # DECLARE
        #   result json;
        # BEGIN
        #   -- Enforce read-only at DB level for this call
        #   SET LOCAL transaction_read_only = on;
        #   SET LOCAL statement_timeout = '30s';
        #   EXECUTE 'SELECT json_agg(t) FROM (' || query_text || ') t' INTO result;
        #   RETURN COALESCE(result, '[]'::json);
        # END;
        # $$ LANGUAGE plpgsql SECURITY DEFINER;
        #
        # GRANT EXECUTE ON FUNCTION execute_readonly_query(text) TO service_role;

        response = client.rpc(
            "execute_readonly_query",
            {"query_text": sql}
        ).execute()

        # Supabase returns the json_agg result as a single value
        raw_data = response.data

        if raw_data is None or raw_data == [] or raw_data == "null":
            return ExecutionResult(
                success=True,
                rows=[],
                row_count=0,
                is_empty=True,
                diagnostic=_build_empty_diagnostic(sql),
            )

        # raw_data should be a list of dicts at this point
        if isinstance(raw_data, list):
            rows = raw_data
        elif isinstance(raw_data, dict):
            rows = [raw_data]
        else:
            rows = []

        logger.info(f"[Layer 6] Query returned {len(rows)} rows.")
        return ExecutionResult(
            success=True,
            rows=rows,
            row_count=len(rows),
            is_empty=len(rows) == 0,
            diagnostic=_build_empty_diagnostic(sql) if len(rows) == 0 else None,
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[Layer 6] Query execution failed: {error_msg}")

        return ExecutionResult(
            success=False,
            rows=[],
            row_count=0,
            error_message=_sanitize_db_error(error_msg),
            is_empty=False,
        )


def _inject_limit_if_missing(sql: str) -> str:
    """
    Adds a LIMIT clause to the SQL if one is not already present.
    Skips injection for aggregate-only queries (COUNT, SUM, etc.)
    that return a single row — no LIMIT needed there.
    """
    sql_upper = sql.upper().strip()

    # Skip LIMIT injection for pure aggregate queries
    is_aggregate_only = (
        "GROUP BY" not in sql_upper
        and any(fn in sql_upper for fn in ["COUNT(", "SUM(", "AVG(", "MAX(", "MIN("])
        and "ORDER BY" not in sql_upper
    )

    if is_aggregate_only:
        return sql

    if "LIMIT" not in sql_upper:
        # Strip trailing semicolon before appending LIMIT
        sql = sql.rstrip().rstrip(";")
        sql = f"{sql}\nLIMIT {config.MAX_RESULT_ROWS}"

    return sql


def _build_empty_diagnostic(sql: str) -> str:
    """
    Produces a helpful message when a query returns no rows.
    Gives the user hints about why results might be empty.
    """
    sql_upper = sql.upper()

    hints = []

    if "WHERE" in sql_upper:
        hints.append("Your query has filters (WHERE clause) that may be too restrictive.")

    if "DELIVERED" in sql_upper or "CANCELLED" in sql_upper or "RETURNED" in sql_upper:
        hints.append("Check that the order status filter matches existing data values.")

    if any(date_keyword in sql_upper for date_keyword in ["BETWEEN", ">=", "<=", "DATE"]):
        hints.append("The date range filter may not match any records in the database.")

    if not hints:
        hints.append("No matching records found. The query executed successfully but returned no data.")

    return " ".join(hints)


def _sanitize_db_error(error_msg: str) -> str:
    """
    Cleans up raw PostgreSQL error messages to make them safe and useful
    to surface to users and feed back into the correction loop.
    Strips internal stack traces and connection strings.
    """
    # Remove internal details that expose infrastructure
    sanitized = error_msg.split("CONTEXT:")[0].strip()
    sanitized = sanitized.split("DETAIL:")[0].strip()

    # Truncate very long error messages
    if len(sanitized) > 400:
        sanitized = sanitized[:400] + "..."

    return sanitized


def build_execution_error_context(error_message: str, sql: str) -> str:
    """
    Builds a structured error context for the correction loop when a DB error occurs.
    Fed back into sql_generator.py as correction_context.
    """
    return (
        f"The following SQL failed at execution time (database error):\n\n"
        f"```sql\n{sql}\n```\n\n"
        f"Database error:\n{error_message}\n\n"
        f"Fix the SQL to resolve this error. Common causes:\n"
        f"- Using a column in SELECT that is not in GROUP BY (for aggregation queries)\n"
        f"- Type mismatch in WHERE clause (e.g. comparing integer column to a string)\n"
        f"- Division by zero in a calculated expression\n"
        f"- Invalid function call for this PostgreSQL version\n"
    )