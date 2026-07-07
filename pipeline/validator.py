"""
pipeline/validator.py  —  Layer 5

Deterministic SQL validation layer. No LLM involved.

Runs four checks in sequence:
  1. Syntax check via sqlglot
  2. Schema validation — tables and columns exist in the loaded schema
  3. Join validation — join conditions match pre-resolved paths
  4. Security scan — no DML (INSERT/UPDATE/DELETE/DROP/TRUNCATE)

On failure, produces a structured, specific error message that is fed back
to sql_generator.py for targeted correction. This is what makes retries converge —
the LLM sees exactly what's wrong and what the valid alternatives are.
"""

from __future__ import annotations
import logging
import re
from typing import Optional

import sqlglot
import sqlglot.errors

from models.schemas import ValidationResult, RetrievedSchema, JoinResolutionResult
from schema.loader import get_cached_schema

logger = logging.getLogger(__name__)

# ── DML / DDL patterns that must never appear ─────────────────────────────────
_FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def validate_sql(
    sql: str,
    schema: RetrievedSchema,
    join_result: JoinResolutionResult,
) -> ValidationResult:
    """
    Runs the full validation pipeline on the generated SQL.

    Args:
        sql: The raw SQL string to validate.
        schema: The retrieved schema (for column/table existence checks).
        join_result: The resolved join paths (for join condition checks).

    Returns:
        ValidationResult with is_valid flag, error list, and security flags.
    """
    errors: list[str]        = []
    security_flags: list[str] = []

    if not sql or not sql.strip():
        return ValidationResult(
            is_valid=False,
            errors=["Generated SQL is empty."],
            security_flags=[],
        )

    # ── 1. Security scan (always first — reject immediately) ─────────────────
    security_flags = _check_security(sql)
    if security_flags:
        logger.warning(f"[Layer 5] Security flags: {security_flags}")
        return ValidationResult(
            is_valid=False,
            errors=["SQL contains forbidden operations."],
            security_flags=security_flags,
        )

    # ── 2. Syntax check ───────────────────────────────────────────────────────
    syntax_errors = _check_syntax(sql)
    errors.extend(syntax_errors)

    # If syntax is broken, don't bother with schema/join checks
    if syntax_errors:
        return ValidationResult(is_valid=False, errors=errors, security_flags=[])

    # ── 3. Schema validation (tables + columns) ───────────────────────────────
    schema_errors = _check_schema(sql, schema)
    errors.extend(schema_errors)

    # ── 4. Join condition validation ──────────────────────────────────────────
    join_errors = _check_joins(sql, join_result)
    errors.extend(join_errors)

    is_valid = len(errors) == 0

    if is_valid:
        logger.info("[Layer 5] SQL passed all validation checks.")
    else:
        logger.info(f"[Layer 5] Validation failed with {len(errors)} error(s): {errors}")

    return ValidationResult(is_valid=is_valid, errors=errors, security_flags=[])


def build_correction_context(
    original_sql: str,
    validation_result: ValidationResult,
    schema: RetrievedSchema,
) -> str:
    """
    Builds a targeted, specific error message for the LLM correction retry.
    This is more effective than just saying "fix the SQL" — it tells the LLM
    exactly what's wrong and what valid alternatives are.
    """
    lines = [
        f"The following SQL has validation errors. Fix ONLY the issues listed below.\n",
        f"Original SQL:\n```sql\n{original_sql}\n```\n",
        "Errors to fix:",
    ]

    for i, error in enumerate(validation_result.errors, 1):
        lines.append(f"  {i}. {error}")

    # Add helpful context from schema for column errors
    full_schema = get_cached_schema()
    for error in validation_result.errors:
        if "Column" in error and "does not exist" in error:
            # Try to extract table name and suggest valid columns
            for table in schema.tables:
                tname = table["table_name"]
                if tname in error:
                    valid_cols = [c["name"] for c in table["columns"]]
                    lines.append(
                        f"\n  ℹ️  Valid columns for '{tname}': {', '.join(valid_cols)}"
                    )

    lines.append("\nGenerate corrected SQL following the same JSON format as before.")
    return "\n".join(lines)


def _check_security(sql: str) -> list[str]:
    """Returns list of forbidden SQL operations found."""
    matches = _FORBIDDEN_PATTERNS.findall(sql)
    flags = []
    for match in set(matches):
        flags.append(f"Forbidden SQL operation detected: {match.upper()}")
    return flags


def _check_syntax(sql: str) -> list[str]:
    """Parses SQL with sqlglot and returns syntax error messages."""
    try:
        statements = sqlglot.parse(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
        if not statements:
            return ["SQL parsed as empty statement."]
        return []
    except sqlglot.errors.ParseError as e:
        return [f"SQL syntax error: {str(e)}"]


def _check_schema(sql: str, schema: RetrievedSchema) -> list[str]:
    """
    Checks that every table and column referenced in the SQL exists
    in the retrieved schema.

    Uses sqlglot AST to extract table and column references.
    """
    errors: list[str] = []

    # Build lookup sets from retrieved schema
    valid_tables: dict[str, set[str]] = {}
    for table in schema.tables:
        valid_tables[table["table_name"].lower()] = {
            col["name"].lower() for col in table["columns"]
        }

    # Also allow from the full schema (for bridge tables added by reachability)
    full_schema = get_cached_schema()
    for tname, tdata in full_schema.items():
        if tname.lower() not in valid_tables:
            valid_tables[tname.lower()] = {col["name"].lower() for col in tdata["columns"]}

    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return []  # Already caught by syntax check

    # Extract table references
    referenced_tables: set[str] = set()
    alias_map: dict[str, str] = {}  # alias → actual table name

    for table_ref in parsed.find_all(sqlglot.exp.Table):
        table_name = table_ref.name.lower() if table_ref.name else ""
        alias = table_ref.alias.lower() if table_ref.alias else ""
        if table_name:
            referenced_tables.add(table_name)
            if alias:
                alias_map[alias] = table_name

    for tname in referenced_tables:
        if tname not in valid_tables:
            errors.append(
                f"Table '{tname}' does not exist in the schema. "
                f"Available tables: {', '.join(sorted(valid_tables.keys()))}"
            )

    # Extract column references
    for col_ref in parsed.find_all(sqlglot.exp.Column):
        col_name = col_ref.name.lower() if col_ref.name else ""
        table_qualifier = col_ref.table.lower() if col_ref.table else ""

        if not col_name or col_name == "*":
            continue

        if table_qualifier:
            # Resolve alias to actual table name
            actual_table = alias_map.get(table_qualifier, table_qualifier)
            if actual_table in valid_tables:
                if col_name not in valid_tables[actual_table]:
                    errors.append(
                        f"Column '{col_name}' does not exist in table '{actual_table}'. "
                        f"Available columns: {', '.join(sorted(valid_tables[actual_table]))}"
                    )
        else:
            # Unqualified column — check if it exists in any referenced table
            found = any(
                col_name in valid_tables.get(t, set())
                for t in referenced_tables
            )
            if not found and referenced_tables:
                errors.append(
                    f"Column '{col_name}' not found in any of the referenced tables: "
                    f"{', '.join(sorted(referenced_tables))}"
                )

    return errors


def _check_joins(sql: str, join_result: JoinResolutionResult) -> list[str]:
    """
    Validates that the JOIN conditions in the SQL use the correct columns
    as specified by the pre-resolved join paths.

    We extract ON conditions from the SQL and compare them against
    the expected join conditions from the graph resolver.
    """
    errors: list[str] = []

    if not join_result.join_fragments:
        return []

    # Build a set of valid join keys (table.column pairs) from resolved paths
    valid_join_keys: set[frozenset] = set()
    for jp in join_result.join_fragments:
        # Parse the join SQL fragment to extract ON condition columns
        try:
            parsed_join = sqlglot.parse_one(f"SELECT 1 FROM {jp.join_sql}", dialect="postgres")
            for join_node in parsed_join.find_all(sqlglot.exp.Join):
                on_condition = join_node.args.get("on")
                if on_condition:
                    cols = [
                        f"{c.table.lower()}.{c.name.lower()}"
                        for c in on_condition.find_all(sqlglot.exp.Column)
                        if c.table
                    ]
                    if len(cols) == 2:
                        valid_join_keys.add(frozenset(cols))
        except Exception:
            continue  # Don't fail validation for parse errors in this check

    # Now check the generated SQL's JOIN ON conditions
    try:
        parsed_sql = sqlglot.parse_one(sql, dialect="postgres")
        for join_node in parsed_sql.find_all(sqlglot.exp.Join):
            on_condition = join_node.args.get("on")
            if not on_condition:
                continue

            used_cols = [
                f"{c.table.lower()}.{c.name.lower()}"
                for c in on_condition.find_all(sqlglot.exp.Column)
                if c.table
            ]
            if len(used_cols) == 2:
                used_pair = frozenset(used_cols)
                if valid_join_keys and used_pair not in valid_join_keys:
                    errors.append(
                        f"JOIN condition {used_cols} does not match any pre-resolved join path. "
                        f"Use only the provided join conditions."
                    )
    except Exception:
        pass  # Syntax already validated

    return errors