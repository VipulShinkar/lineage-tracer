from pathlib import Path

from lineage_parser.graph import NodeKind
from lineage_parser.xml import parse_xml_lineage

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_ssis_format_autodetect_and_lineage():
    result = parse_xml_lineage(_load("sample.dtsx"))
    assert result.format_detected == "ssis"
    assert not result.errors

    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    assert ("raw.customers", "stg.customers") in edge_pairs


def test_ssis_component_chain_present_at_full_detail():
    result = parse_xml_lineage(_load("sample.dtsx"))
    component_labels = {n.label for n in result.graph.nodes.values() if n.kind == NodeKind.COMPONENT}
    assert {"OLE DB Source", "Derived Column", "OLE DB Destination"} <= component_labels


def test_informatica_format_autodetect_and_lineage():
    result = parse_xml_lineage(_load("sample_informatica.xml"))
    assert result.format_detected == "informatica"

    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    edge_pairs = {(tables.nodes[e.source].label, tables.nodes[e.target].label) for e in tables.edges}
    assert ("SRC_CUSTOMERS", "TGT_CUSTOMERS") in edge_pairs


def test_informatica_column_level_lineage():
    result = parse_xml_lineage(_load("sample_informatica.xml"))
    edge_labels = {
        (result.graph.nodes[e.source].label, result.graph.nodes[e.target].label)
        for e in result.graph.edges
        if result.graph.nodes[e.source].kind == NodeKind.COLUMN
    }
    assert ("SRC_CUSTOMERS.CUST_ID", "EXP_Transform.CUST_ID") in edge_labels


def test_generic_format_autodetect_and_lineage():
    result = parse_xml_lineage(_load("sample_generic.xml"))
    assert result.format_detected == "generic"

    edge_pairs = {(result.graph.nodes[e.source].label, result.graph.nodes[e.target].label) for e in result.graph.edges}
    assert ("raw.customers", "stg.customers") in edge_pairs
    assert ("raw.orders", "mart.order_summary") in edge_pairs
    assert ("raw.order_items", "mart.order_summary") in edge_pairs


def test_direction_reversal_on_collapsed_graph():
    result = parse_xml_lineage(_load("sample.dtsx"))
    tables = result.graph.collapse_to_kind(NodeKind.TABLE)
    forward = {(e.source, e.target) for e in tables.oriented_edges("source_to_target")}
    backward = {(e.source, e.target) for e in tables.oriented_edges("target_to_source")}
    assert forward == {(t, s) for (s, t) in backward}


def test_invalid_xml_reports_error_without_raising():
    result = parse_xml_lineage("<not-closed>")
    assert result.graph.is_empty()
    assert result.errors
