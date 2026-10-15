"""Informatica PowerCenter mapping XML export -> LineageGraph.

Standard PowerCenter export shape:
    <POWERMART><REPOSITORY><FOLDER>
      <SOURCE NAME="SRC_X">...<SOURCEFIELD NAME="..."/></SOURCE>
      <TARGET NAME="TGT_X">...<TARGETFIELD NAME="..."/></TARGET>
      <MAPPING NAME="m_...">
        <INSTANCE NAME="SRC_X" TRANSFORMATION_TYPE="Source Qualifier" .../>
        <INSTANCE NAME="TGT_X" TRANSFORMATION_TYPE="Target Definition" .../>
        <CONNECTOR FROMINSTANCE="A" FROMFIELD="c1" TOINSTANCE="B" TOFIELD="c2"/>
      </MAPPING>
    </FOLDER></REPOSITORY></POWERMART>

CONNECTOR elements give exact column-level edges between mapping instances,
already chained end-to-end from source through every transformation to the
target, so no positional guessing is needed. Instances that share a name with
a SOURCE/TARGET definition are linked to that physical table.
"""

from __future__ import annotations

from lxml import etree

from lineage_parser.graph import LineageGraph, NodeKind


def parse_informatica(root: etree._Element) -> LineageGraph:
    graph = LineageGraph()

    source_names = {s.get("NAME") for s in root.findall(".//SOURCE") if s.get("NAME")}
    target_names = {t.get("NAME") for t in root.findall(".//TARGET") if t.get("NAME")}
    for name in source_names | target_names:
        graph.add_node(f"table:{name}", NodeKind.TABLE, name)

    for mapping in root.findall(".//MAPPING"):
        mapping_name = mapping.get("NAME") or "mapping"

        instance_types: dict[str, str] = {}
        for inst in mapping.findall("./INSTANCE"):
            inst_name = inst.get("NAME")
            if not inst_name:
                continue
            instance_types[inst_name] = inst.get("TRANSFORMATION_TYPE") or ""
            comp_id = f"component:{mapping_name}.{inst_name}"
            graph.add_node(comp_id, NodeKind.COMPONENT, inst_name)

            if inst_name in source_names:
                graph.add_edge(f"table:{inst_name}", comp_id, relation="flows_to", detail="informatica-source")
            if inst_name in target_names:
                graph.add_edge(comp_id, f"table:{inst_name}", relation="flows_to", detail="informatica-target")

        for connector in mapping.findall("./CONNECTOR"):
            from_inst = connector.get("FROMINSTANCE")
            to_inst = connector.get("TOINSTANCE")
            from_field = connector.get("FROMFIELD")
            to_field = connector.get("TOFIELD")
            if not from_inst or not to_inst:
                continue

            from_comp_id = f"component:{mapping_name}.{from_inst}"
            to_comp_id = f"component:{mapping_name}.{to_inst}"
            graph.add_node(from_comp_id, NodeKind.COMPONENT, from_inst)
            graph.add_node(to_comp_id, NodeKind.COMPONENT, to_inst)
            graph.add_edge(from_comp_id, to_comp_id, relation="flows_to", detail="informatica-connector")

            if from_field and to_field:
                from_col_id = _column_id(from_inst, from_field, source_names, target_names)
                to_col_id = _column_id(to_inst, to_field, source_names, target_names)
                graph.add_node(from_col_id, NodeKind.COLUMN, f"{from_inst}.{from_field}")
                graph.add_node(to_col_id, NodeKind.COLUMN, f"{to_inst}.{to_field}")
                graph.add_edge(from_col_id, to_col_id, relation="flows_to")

    return graph


def _column_id(instance_name: str, field_name: str, source_names: set[str], target_names: set[str]) -> str:
    prefix = "table" if instance_name in source_names or instance_name in target_names else "component"
    return f"{prefix}:{instance_name}.{field_name}"
