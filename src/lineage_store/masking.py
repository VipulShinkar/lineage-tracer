"""Identifier masking (mirrors the SQL functions mask_cpty / mask_key used by the agent views)."""


def mask_counterparty(v: str) -> str:
    """CPTY-00012764 -> CPTY-•••2764"""
    return f"{v.rsplit('-', 1)[0]}-•••{v[-4:]}"


def mask_key(v: str) -> str:
    """LOS-FAC-00123458 -> LOS-FAC-00••••58 ; CBS-ACC-71234502 -> CBS-ACC-7•••••02
    Keeps the leading zeros (or the first character) and the last two characters."""
    head, seg = v.rsplit("-", 1)
    keep = (len(seg) - len(seg.lstrip("0"))) or 1
    return f"{head}-{seg[:keep]}{'•' * (len(seg) - keep - 2)}{seg[-2:]}"
