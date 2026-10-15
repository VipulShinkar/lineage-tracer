from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from lineage_parser.graph import LineageGraph
from lineage_parser.xml.detect import detect_xml_format
from lineage_parser.xml.generic import parse_generic
from lineage_parser.xml.informatica import parse_informatica
from lineage_parser.xml.ssis import parse_ssis


@dataclass
class XmlParseResult:
    graph: LineageGraph
    format_detected: str
    errors: list[str] = field(default_factory=list)


def parse_xml_lineage(xml_text: str, xml_format: str = "auto") -> XmlParseResult:
    errors: list[str] = []

    # Real-world/hand-authored XML often violates strict rules lxml enforces by
    # default (e.g. "--" inside comments, which is invalid per the XML spec but
    # common in decorative comment banners). Parse leniently and only give up
    # if recovery still can't produce a root element.
    lenient_parser = etree.XMLParser(recover=True, resolve_entities=False)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=lenient_parser)
    if root is None:
        parse_errors = [str(e) for e in lenient_parser.error_log]
        return XmlParseResult(graph=LineageGraph(), format_detected="unknown", errors=[f"XML parse error: {e}" for e in parse_errors] or ["XML could not be parsed"])
    if lenient_parser.error_log:
        errors.append(f"XML had {len(lenient_parser.error_log)} minor syntax issue(s) that were recovered from automatically.")

    fmt = xml_format if xml_format != "auto" else detect_xml_format(root)

    parsers = {
        "ssis": parse_ssis,
        "informatica": parse_informatica,
        "generic": parse_generic,
    }
    parser = parsers.get(fmt)
    if parser is None:
        return XmlParseResult(graph=LineageGraph(), format_detected=fmt, errors=[f"Unknown xml_format: {fmt!r}"])

    graph = parser(root)
    if graph.is_empty():
        errors.append(f"No lineage relationships found (detected format: {fmt}). If this is a custom schema, a sample would help tailor the parser.")
    return XmlParseResult(graph=graph, format_detected=fmt, errors=errors)
