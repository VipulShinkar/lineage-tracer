"""Heuristic lineage extraction for arbitrary/custom XML that isn't SSIS or
Informatica. This is best-effort: it looks for the common ETL-config idiom of
a "block" element containing source-like tags and target-like tags, e.g.:

    <mapping><source table="A"/><target table="B"/></mapping>
    <transform name="t1"><from table="A"/><to table="B"/></transform>
    <entry><input ref="A"/><output ref="B"/></entry>

For each such block, every source entity is linked to every target entity
found within it. If a real schema sample is available, prefer writing a
purpose-built parser (see xml/ssis.py or xml/informatica.py for the pattern)
instead of relying on this heuristic.
"""

from __future__ import annotations

from lxml import etree

from lineage_parser.graph import LineageGraph, NodeKind
from lineage_parser.xml.detect import local_name

_SOURCE_TAGS = {"source", "sources", "from", "src", "input", "inputs"}
_TARGET_TAGS = {"target", "targets", "to", "tgt", "output", "outputs", "destination", "dest", "destinations"}
_NAME_ATTRS = ("table", "tableName", "name", "ref", "object", "entity", "id")


def parse_generic(root: etree._Element) -> LineageGraph:
    graph = LineageGraph()

    for block in _find_blocks(root):
        block_label = block.get("name") or block.get("id") or local_name(block.tag)
        sources = _entities(block, _SOURCE_TAGS)
        targets = _entities(block, _TARGET_TAGS)

        for s in sources:
            graph.add_node(f"table:{s}", NodeKind.TABLE, s)
        for t in targets:
            graph.add_node(f"table:{t}", NodeKind.TABLE, t)

        for s in sources:
            for t in targets:
                if s != t:
                    graph.add_edge(f"table:{s}", f"table:{t}", relation="flows_to", detail=block_label)

    return graph


def _has_source_and_target(el: etree._Element) -> bool:
    has_source = False
    has_target = False
    for node in el.iter():
        tag = local_name(node.tag).lower()
        if tag in _SOURCE_TAGS:
            has_source = True
        elif tag in _TARGET_TAGS:
            has_target = True
        if has_source and has_target:
            return True
    return False


def _find_blocks(root: etree._Element) -> list[etree._Element]:
    """Find the deepest elements that each contain both source-tagged and
    target-tagged descendants, treating each as one independent lineage unit."""
    blocks: list[etree._Element] = []

    def walk(el: etree._Element) -> None:
        if _has_source_and_target(el):
            child_blocks = [c for c in el if _has_source_and_target(c)]
            if child_blocks:
                for c in el:
                    walk(c)
            else:
                blocks.append(el)
        else:
            for c in el:
                walk(c)

    walk(root)
    return blocks


def _entities(block: etree._Element, tags: set[str]) -> list[str]:
    names: list[str] = []
    for node in block.iter():
        tag = local_name(node.tag).lower()
        if tag not in tags:
            continue
        name = _extract_name(node)
        if name:
            names.append(name)
        else:
            # plural/container element (e.g. <sources>) - look at its direct children
            for child in node:
                child_name = _extract_name(child)
                if child_name:
                    names.append(child_name)
    return names


def _extract_name(el: etree._Element) -> str | None:
    for attr in _NAME_ATTRS:
        val = el.get(attr)
        if val and val.strip():
            return val.strip()
    if el.text and el.text.strip():
        return el.text.strip()
    return None
