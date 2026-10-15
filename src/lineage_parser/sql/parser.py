"""SQL -> LineageGraph extraction using sqlglot.

Scope (deterministic, no schema/catalog required):
  - Table-level lineage for CREATE TABLE/VIEW AS SELECT, INSERT ... SELECT,
    MERGE INTO ... USING ..., UPDATE ... FROM ...
  - Column-level lineage for CTAS / INSERT-SELECT statements with explicit
    (non `SELECT *`) projections, including transitive resolution through CTEs.
  - MERGE/UPDATE are captured at table-level only (column-level for those is
    out of scope: it would require full schema knowledge to resolve `*`-style
    matches reliably).

Statements sqlglot cannot parse under the requested dialect are retried with
no dialect, and if that also fails they are reported in `errors` rather than
aborting the whole file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from lineage_parser.graph import LineageGraph, NodeKind


@dataclass
class SqlParseResult:
    graph: LineageGraph
    errors: list[str] = field(default_factory=list)


def parse_sql_lineage(sql_text: str, dialect: str = "tsql") -> SqlParseResult:
    graph = LineageGraph()
    errors: list[str] = []

    statements = _parse_statements(sql_text, dialect, errors)
    for stmt in statements:
        try:
            _process_statement(stmt, graph)
        except Exception as exc:  # noqa: BLE001 - isolate one bad statement from the rest
            errors.append(f"Failed to extract lineage from statement: {exc}")

    return SqlParseResult(graph=graph, errors=errors)


def _parse_statements(sql_text: str, dialect: str, errors: list[str]) -> list[exp.Expression]:
    try:
        parsed = sqlglot.parse(sql_text, dialect=dialect)
        statements = [s for s in parsed if s is not None]
        if statements:
            return statements
    except Exception:  # noqa: BLE001 - fall back to per-statement parsing below
        pass

    # Parse statement-by-statement so one bad statement doesn't lose the rest of the file.
    statements: list[exp.Expression] = []
    for chunk in _split_statements(sql_text):
        if not chunk.strip():
            continue
        parsed_stmt = None
        for try_dialect in (dialect, None):
            try:
                parsed_stmt = sqlglot.parse_one(chunk, dialect=try_dialect)
                break
            except Exception:  # noqa: BLE001
                continue
        if parsed_stmt is not None:
            statements.append(parsed_stmt)
        else:
            errors.append(f"Could not parse statement (dialect={dialect}): {chunk.strip()[:120]}")
    return statements


def _split_statements(sql_text: str) -> list[str]:
    """Split on top-level semicolons using sqlglot's tokenizer, so semicolons
    inside string literals/comments don't break the split."""
    tokens = sqlglot.tokens.Tokenizer().tokenize(sql_text)
    chunks: list[str] = []
    start = 0
    for tok in tokens:
        if tok.token_type == sqlglot.tokens.TokenType.SEMICOLON:
            end = tok.end + 1 if hasattr(tok, "end") else None
            if end is None:
                continue
            chunks.append(sql_text[start:end])
            start = end
    tail = sql_text[start:]
    if tail.strip():
        chunks.append(tail)
    return chunks or [sql_text]


def _process_statement(stmt: exp.Expression, graph: LineageGraph) -> None:
    target_name, select_expr, source_hint_tables = _extract_target_and_source(stmt)
    if target_name is None:
        return

    target_id = _table_id(target_name)
    graph.add_node(target_id, NodeKind.TABLE, target_name)

    # CTEs may be attached to the statement itself (e.g. `WITH x AS (...) INSERT INTO ...`)
    # rather than nested inside the SELECT, so collect from the whole statement.
    cte_defs = _collect_ctes(stmt)
    physical_sources: set[str] = set()

    if select_expr is not None:
        for table_name in _physical_tables_in(select_expr, cte_defs):
            physical_sources.add(table_name)
    for table_name in source_hint_tables:
        physical_sources.update(_resolve_physical(table_name, cte_defs))

    for src_table in physical_sources:
        if src_table == target_name:
            continue
        src_id = _table_id(src_table)
        graph.add_node(src_id, NodeKind.TABLE, src_table)
        graph.add_edge(src_id, target_id, relation="flows_to", detail=stmt.__class__.__name__)

    if isinstance(select_expr, exp.Select):
        _extract_column_lineage(target_name, select_expr, cte_defs, graph)


def _extract_target_and_source(stmt: exp.Expression):
    """Returns (target_table_name | None, select_expr | None, extra_source_table_names)."""
    if isinstance(stmt, exp.Create):
        kind = (stmt.args.get("kind") or "").upper()
        target = stmt.this
        table_name = _table_name_of(target)
        select = stmt.expression if isinstance(stmt.expression, (exp.Select, exp.Union)) else None
        if kind in ("TABLE", "VIEW") and table_name and select is not None:
            return table_name, select, []
        return None, None, []

    if isinstance(stmt, exp.Insert):
        table_name = _table_name_of(stmt.this)
        select = stmt.expression if isinstance(stmt.expression, (exp.Select, exp.Union)) else None
        if table_name:
            return table_name, select, []
        return None, None, []

    if isinstance(stmt, exp.Merge):
        table_name = _table_name_of(stmt.this)
        using = stmt.args.get("using")
        extra = [_qualified_name(t) for t in using.find_all(exp.Table)] if using is not None else []
        if table_name:
            return table_name, None, extra
        return None, None, []

    if isinstance(stmt, exp.Update):
        table_name = _table_name_of(stmt.this)
        from_clause = stmt.args.get("from_")
        joins = stmt.args.get("joins") or []
        extra = []
        if from_clause is not None:
            extra.extend(_qualified_name(t) for t in from_clause.find_all(exp.Table))
        for j in joins:
            extra.extend(_qualified_name(t) for t in j.find_all(exp.Table))
        if table_name:
            return table_name, None, extra
        return None, None, []

    return None, None, []


def _table_name_of(node: exp.Expression | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, exp.Table):
        return _qualified_name(node)
    if isinstance(node, exp.Schema):
        return _table_name_of(node.this)
    table = node.find(exp.Table)
    return _table_name_of(table) if table else None


def _qualified_name(table: exp.Table) -> str:
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    return ".".join(parts)


def _table_id(name: str) -> str:
    return f"table:{name}"


def _collect_ctes(select_expr: exp.Expression | None) -> dict[str, exp.Select]:
    ctes: dict[str, exp.Select] = {}
    if select_expr is None:
        return ctes
    for cte in select_expr.find_all(exp.CTE):
        inner = cte.this
        if isinstance(inner, exp.Select):
            ctes[cte.alias_or_name] = inner
    return ctes


def _physical_tables_in(select_expr: exp.Expression, ctes: dict[str, exp.Select]) -> set[str]:
    result: set[str] = set()
    for table in select_expr.find_all(exp.Table):
        result.update(_resolve_physical(_qualified_name(table), ctes))
    return result


def _resolve_physical(name: str, ctes: dict[str, exp.Select]) -> set[str]:
    """A referenced name is either a physical table, or a CTE alias that should be
    expanded to the physical tables it ultimately reads from."""
    if name in ctes:
        underlying = set()
        for table in ctes[name].find_all(exp.Table):
            qname = _qualified_name(table)
            if qname != name:
                underlying.update(_resolve_physical(qname, ctes))
        return underlying
    return {name}


def _alias_map(select_expr: exp.Select) -> dict[str, str]:
    """Maps FROM/JOIN aliases (or bare table names) to the name used in the query
    (which may itself be a CTE alias, resolved later)."""
    mapping: dict[str, str] = {}
    from_clause = select_expr.args.get("from_")
    joins = select_expr.args.get("joins") or []
    clauses = ([from_clause] if from_clause else []) + list(joins)
    for clause in clauses:
        for table in clause.find_all(exp.Table):
            mapping[table.alias_or_name] = _qualified_name(table)
    return mapping


def _value_columns(expr: exp.Expression) -> list[exp.Column]:
    """Find Column refs that actually contribute to the produced value, skipping
    WHERE/HAVING/JOIN-ON predicate columns of any nested subquery - those are
    filter/correlation conditions, not data sources, so `find_all` (which walks
    everything indiscriminately) over-reports lineage for correlated subqueries."""
    if isinstance(expr, exp.Column):
        return [expr]
    if isinstance(expr, exp.Select):
        cols: list[exp.Column] = []
        for proj in expr.expressions:
            cols.extend(_value_columns(proj))
        return cols

    cols = []
    for child in expr.args.values():
        children = child if isinstance(child, list) else [child]
        for c in children:
            if isinstance(c, exp.Expression):
                cols.extend(_value_columns(c))
    return cols


def _extract_column_lineage(
    target_table: str,
    select_expr: exp.Select,
    ctes: dict[str, exp.Select],
    graph: LineageGraph,
    _seen: set[tuple[str, str]] | None = None,
) -> None:
    seen = _seen if _seen is not None else set()
    alias_map = _alias_map(select_expr)
    single_source = next(iter(alias_map.values())) if len(alias_map) == 1 else None

    for projection in select_expr.expressions:
        if isinstance(projection, exp.Star) or (isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)):
            continue  # `SELECT *` can't be expanded without a schema; skip column-level here.

        output_name = projection.alias_or_name
        if not output_name:
            continue
        value_expr = projection.this if isinstance(projection, exp.Alias) else projection

        target_col_id = f"table:{target_table}.{output_name}"
        found_any = False
        for column in _value_columns(value_expr):
            found_any = True
            _link_source_column(
                column, alias_map, single_source, ctes, target_col_id, graph, seen
            )

        if found_any:
            graph.add_node(target_col_id, NodeKind.COLUMN, f"{target_table}.{output_name}")


def _link_source_column(
    column: exp.Column,
    alias_map: dict[str, str],
    single_source: str | None,
    ctes: dict[str, exp.Select],
    target_col_id: str,
    graph: LineageGraph,
    seen: set[tuple[str, str]],
) -> None:
    ref_alias = column.table
    real_name = alias_map.get(ref_alias, ref_alias) if ref_alias else single_source
    if not real_name:
        return  # ambiguous (multiple sources, no qualifier) - skip rather than guess

    key = (real_name, column.name, target_col_id)
    if key in seen:
        return
    seen.add(key)

    if real_name in ctes:
        # Recurse through the CTE: find the projection in the CTE that produced
        # `column.name`, and continue resolving from there.
        cte_select = ctes[real_name]
        for proj in cte_select.expressions:
            if proj.alias_or_name == column.name:
                value_expr = proj.this if isinstance(proj, exp.Alias) else proj
                inner_alias_map = _alias_map(cte_select)
                inner_single = next(iter(inner_alias_map.values())) if len(inner_alias_map) == 1 else None
                for inner_col in _value_columns(value_expr):
                    _link_source_column(
                        inner_col, inner_alias_map, inner_single, ctes, target_col_id, graph, seen
                    )
                break
        return

    src_col_id = f"table:{real_name}.{column.name}"
    graph.add_node(src_col_id, NodeKind.COLUMN, f"{real_name}.{column.name}")
    graph.add_edge(src_col_id, target_col_id, relation="flows_to")
