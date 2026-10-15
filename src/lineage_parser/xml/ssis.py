"""SSIS (.dtsx) package -> LineageGraph.

SSIS Data Flow Tasks are represented as XML `<component>` elements wired
together by `<path>` elements. Each component's `<inputs>`/`<outputs>`
children carry a `refId` attribute whose value is exactly the same ID string
used by `<path startId="..." endId="...">` to reference it, so component
edges are resolved by matching those refIds rather than guessing from
position/order.

Source/destination components additionally get linked to the physical
table/query they read from or write to, read from well-known property names
(OpenRowset, SqlCommand, TableOrViewName, FileName, ...).
"""

from __future__ import annotations

from lxml import etree

from lineage_parser.graph import LineageGraph, NodeKind

_EXTERNAL_NAME_PROPERTIES = (
    "OpenRowset",
    "TableOrViewName",
    "SqlCommand",
    "SqlCommandVar",
    "FileName",
    "ConnectionString",
)


def parse_ssis(root: etree._Element) -> LineageGraph:
    graph = LineageGraph()

    components = root.findall(".//{*}component")
    refid_to_component: dict[str, str] = {}

    for comp in components:
        comp_name = comp.get("name") or comp.get("refId") or "component"
        comp_id = f"component:{comp_name}"
        graph.add_node(comp_id, NodeKind.COMPONENT, comp_name)

        for io_el in comp.findall("./{*}inputs/{*}input") + comp.findall("./{*}outputs/{*}output"):
            ref_id = io_el.get("refId")
            if ref_id:
                refid_to_component[ref_id] = comp_name
            for ext_col in io_el.findall("./{*}externalMetadataColumns/{*}externalMetadataColumn"):
                ext_ref = ext_col.get("refId")
                if ext_ref:
                    refid_to_component[ext_ref] = comp_name

        class_id = (comp.get("componentClassID") or "").lower()
        external_name = _find_external_name(comp)
        if external_name:
            table_id = f"table:{external_name}"
            graph.add_node(table_id, NodeKind.TABLE, external_name)
            if "destination" in class_id or "target" in class_id:
                graph.add_edge(comp_id, table_id, relation="flows_to", detail="ssis-destination")
            else:
                graph.add_edge(table_id, comp_id, relation="flows_to", detail="ssis-source")

    for path in root.findall(".//{*}path"):
        start_id = path.get("startId")
        end_id = path.get("endId")
        start_comp = refid_to_component.get(start_id)
        end_comp = refid_to_component.get(end_id)
        if start_comp and end_comp and start_comp != end_comp:
            graph.add_edge(f"component:{start_comp}", f"component:{end_comp}", relation="flows_to", detail="ssis-path")

    return graph


def _find_external_name(comp: etree._Element) -> str | None:
    for prop in comp.findall("./{*}properties/{*}property"):
        prop_name = prop.get("name")
        if prop_name in _EXTERNAL_NAME_PROPERTIES and (prop.text or "").strip():
            return prop.text.strip()
    return None
