"""
schema/graph.py

Builds a directed FK relationship graph from the loaded schema and resolves
correct join paths between any two tables using BFS.

This is a fully deterministic component — no LLM involved.
The join SQL fragments produced here are injected directly into the LLM prompt
so the LLM never has to guess join conditions.

Graph structure:
  Nodes → table names
  Edges → FK relationships with join SQL attached (bidirectional so BFS works in both directions)
"""

from __future__ import annotations
from collections import deque
import logging
from models.schemas import JoinPath, JoinResolutionResult

logger = logging.getLogger(__name__)

# ── In-memory graph (built once at startup) ──────────────────────────────────
# adjacency: { "orders": [{"table": "customers", "join_sql": "...", "via": "customer_id"}, ...] }
_graph: dict[str, list[dict]] = {}


def build_graph(schema: dict) -> None:
    """
    Builds the in-memory FK graph from the loaded schema dict.
    Call this once at startup after load_schema().

    For every FK column in the schema, we add two directed edges:
      A → B  (forward FK direction)
      B → A  (reverse, so BFS can traverse in both directions)
    """
    global _graph
    _graph = {}

    for table_name, table_data in schema.items():
        if table_name not in _graph:
            _graph[table_name] = []

        for col in table_data["columns"]:
            if not col["is_fk"]:
                continue

            ref_table = col["references_table"]
            ref_col   = col["references_column"]
            local_col = col["name"]

            if ref_table not in _graph:
                _graph[ref_table] = []

            # Forward edge: table_name → ref_table
            forward_join = (
                f"{table_name} JOIN {ref_table} "
                f"ON {table_name}.{local_col} = {ref_table}.{ref_col}"
            )
            _graph[table_name].append({
                "table":    ref_table,
                "join_sql": forward_join,
                "local_col": local_col,
                "ref_col":   ref_col,
            })

            # Reverse edge: ref_table → table_name
            reverse_join = (
                f"{ref_table} JOIN {table_name} "
                f"ON {ref_table}.{ref_col} = {table_name}.{local_col}"
            )
            _graph[ref_table].append({
                "table":    table_name,
                "join_sql": reverse_join,
                "local_col": ref_col,
                "ref_col":   local_col,
            })

    logger.info(f"Schema graph built: {len(_graph)} nodes.")


def get_all_tables() -> list[str]:
    return list(_graph.keys())


def resolve_joins(tables: list[str]) -> JoinResolutionResult:
    """
    Given a list of tables needed for a query, finds the join paths
    connecting all of them using BFS on the schema graph.

    Strategy:
      1. Pick the first table as the anchor (starting node).
      2. For each remaining table, BFS from anchor to find shortest path.
      3. Collect all intermediate tables and join SQL fragments.
      4. If multiple paths exist between a pair, flag as ambiguous.
      5. If no path exists, flag as unreachable.

    Returns a JoinResolutionResult with all join fragments ready to inject into the LLM prompt.
    """
    if len(tables) == 0:
        return JoinResolutionResult(join_fragments=[], ambiguous_paths=[], unreachable_pairs=[])

    join_fragments: list[JoinPath] = []
    ambiguous_paths: list[dict]    = []
    unreachable_pairs: list[dict]  = []

    # For multi-table queries, find join path from each new table to an already-connected set
    connected_tables = {tables[0]}

    for target_table in tables[1:]:
        if target_table in connected_tables:
            continue  # already connected

        # BFS from any connected table to target_table
        path_result = _bfs_shortest_path(connected_tables, target_table)

        if path_result is None:
            unreachable_pairs.append({
                "from_set": list(connected_tables),
                "to":       target_table,
                "note":     f"No FK path found between {list(connected_tables)} and {target_table}."
            })
            logger.warning(f"No join path found to {target_table} from {connected_tables}")
            continue

        # Check if there are multiple equally short paths (ambiguity)
        all_paths = _bfs_all_shortest_paths(connected_tables, target_table)
        if len(all_paths) > 1:
            ambiguous_paths.append({
                "from_set": list(connected_tables),
                "to":       target_table,
                "paths":    [p["path"] for p in all_paths],
                "note":     f"Multiple join paths found to {target_table}. Using shortest."
            })

        join_fragments.append(path_result)

        # Add all tables in the path to connected set
        for t in path_result.path:
            connected_tables.add(t)
        connected_tables.add(target_table)

    return JoinResolutionResult(
        join_fragments=join_fragments,
        ambiguous_paths=ambiguous_paths,
        unreachable_pairs=unreachable_pairs,
    )


def _bfs_shortest_path(
    start_set: set[str],
    target: str
) -> JoinPath | None:
    """
    BFS from any table in start_set to target.
    Returns the shortest JoinPath or None if unreachable.
    """
    # Queue entries: (current_table, path_so_far, join_sqls_so_far)
    queue: deque = deque()
    visited: set = set()

    for start in start_set:
        queue.append((start, [start], []))
        visited.add(start)

    while queue:
        current, path, joins = queue.popleft()

        if current == target:
            # Reconstruct the JoinPath
            from_table = path[0]
            join_sql = _build_chain_join(path, joins)
            return JoinPath(
                from_table=from_table,
                to_table=target,
                join_sql=join_sql,
                path=path,
            )

        for neighbor in _graph.get(current, []):
            next_table = neighbor["table"]
            if next_table in visited:
                continue
            visited.add(next_table)
            queue.append((
                next_table,
                path + [next_table],
                joins + [neighbor["join_sql"]]
            ))

    return None


def _bfs_all_shortest_paths(
    start_set: set[str],
    target: str
) -> list[dict]:
    """
    BFS to find ALL shortest paths from any start to target.
    Used to detect ambiguity (multiple valid join routes).
    Returns list of {"path": [...], "joins": [...]} dicts.
    """
    results: list[dict] = []
    min_length: int | None = None

    queue: deque = deque()
    # Track visited at each depth level to allow parallel paths
    visited_at_depth: dict[str, int] = {}

    for start in start_set:
        queue.append((start, [start], [], 0))
        visited_at_depth[start] = 0

    while queue:
        current, path, joins, depth = queue.popleft()

        if min_length is not None and depth > min_length:
            break

        if current == target:
            results.append({"path": path, "joins": joins})
            min_length = depth
            continue

        for neighbor in _graph.get(current, []):
            next_table = neighbor["table"]
            next_depth = depth + 1
            prev_depth = visited_at_depth.get(next_table)

            if prev_depth is None or prev_depth == next_depth:
                visited_at_depth[next_table] = next_depth
                queue.append((
                    next_table,
                    path + [next_table],
                    joins + [neighbor["join_sql"]],
                    next_depth
                ))

    return results


def _build_chain_join(path: list[str], joins: list[str]) -> str:
    """
    Builds a clean multi-table JOIN SQL string from a path.
    e.g. path = [orders, customers] → "orders JOIN customers ON orders.customer_id = customers.customer_id"
    For longer paths, collapses the intermediate JOINs cleanly.
    """
    if not joins:
        return path[0]

    # The first element of each join_sql already contains the full JOIN clause
    # We take the base table from path[0] and chain joins after
    base = path[0]
    chain_parts = []
    for join_sql in joins:
        # Each join_sql looks like: "A JOIN B ON A.x = B.y"
        # We only want the "JOIN B ON A.x = B.y" part after the first table
        parts = join_sql.split(" JOIN ", 1)
        if len(parts) == 2:
            chain_parts.append(f"JOIN {parts[1]}")

    return base + " " + " ".join(chain_parts)


def format_joins_for_prompt(result: JoinResolutionResult) -> str:
    """
    Formats the JoinResolutionResult into a clean string block
    ready to be injected into the LLM SQL generation prompt.
    """
    lines = ["## Pre-resolved Join Paths (use these exactly):"]

    for jp in result.join_fragments:
        lines.append(f"- {jp.from_table} → {jp.to_table}: {jp.join_sql}")

    if result.ambiguous_paths:
        lines.append("\n## ⚠️ Ambiguous join paths detected (multiple valid routes):")
        for ap in result.ambiguous_paths:
            lines.append(f"- To reach {ap['to']}: {ap['note']}")
            for i, p in enumerate(ap["paths"], 1):
                lines.append(f"  Option {i}: {' → '.join(p)}")

    if result.unreachable_pairs:
        lines.append("\n## ⚠️ Unreachable tables (no FK path found):")
        for up in result.unreachable_pairs:
            lines.append(f"- {up['to']}: {up['note']}")

    return "\n".join(lines)