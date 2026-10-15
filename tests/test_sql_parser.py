from pathlib import Path

from lineage_parser.graph import NodeKind
from lineage_parser.sql.parser import parse_sql_lineage

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_ctas_table_lineage():
    result = parse_sql_lineage(_load("sample.sql"))
    assert not result.errors
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    assert ("raw.customers", "stg.customers") in edge_pairs


def test_insert_select_with_cte_table_lineage():
    result = parse_sql_lineage(_load("sample.sql"))
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    # active_orders is a CTE over raw.orders; it should resolve to the physical table.
    assert ("raw.orders", "mart.customer_orders") in edge_pairs
    assert ("stg.customers", "mart.customer_orders") in edge_pairs


def test_merge_and_update_table_lineage():
    result = parse_sql_lineage(_load("sample.sql"))
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    assert ("stg.customers", "mart.customer_dim") in edge_pairs
    assert ("raw.customers", "mart.customer_dim") in edge_pairs


def test_column_level_lineage_through_cte():
    result = parse_sql_lineage(_load("sample.sql"))
    col_ids = {n.label for n in result.graph.nodes.values() if n.kind == NodeKind.COLUMN}
    assert "mart.customer_orders.order_id" in col_ids
    assert "raw.orders.order_id" in col_ids
    edge_labels = {
        (result.graph.nodes[e.source].label, result.graph.nodes[e.target].label)
        for e in result.graph.edges
        if result.graph.nodes[e.source].kind == NodeKind.COLUMN
    }
    assert ("raw.orders.order_id", "mart.customer_orders.order_id") in edge_labels


def test_direction_reversal():
    result = parse_sql_lineage(_load("sample.sql"))
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    forward = {(e.source, e.target) for e in tables.oriented_edges("source_to_target")}
    backward = {(e.source, e.target) for e in tables.oriented_edges("target_to_source")}
    assert forward == {(t, s) for (s, t) in backward}


def test_malformed_statement_does_not_abort_whole_file():
    sql = "INSERT INTO good.tbl SELECT a FROM raw.tbl;\nSELECT * FROM (SELECT * FROM broken;\n"
    result = parse_sql_lineage(sql)
    assert result.errors  # the bad statement is reported...
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    assert ("raw.tbl", "good.tbl") in edge_pairs  # ...but the good one still parses
