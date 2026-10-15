"""Best-effort detection of which XML "flavor" a file is, so the right
lineage parser can be dispatched automatically."""

from __future__ import annotations

from lxml import etree


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def detect_xml_format(root: etree._Element) -> str:
    tag = local_name(root.tag).lower()
    nsmap_values = " ".join(v.lower() for v in root.nsmap.values() if v)

    if tag == "executable" and ("sqlserver/dts" in nsmap_values or any("dts" in k.lower() for k in root.nsmap if k)):
        return "ssis"
    if root.find(".//{*}Executable") is not None and "dts" in nsmap_values:
        return "ssis"

    if tag == "powermart":
        return "informatica"
    if root.find(".//MAPPING") is not None and (root.find(".//SOURCE") is not None or root.find(".//TARGET") is not None):
        return "informatica"

    return "generic"
