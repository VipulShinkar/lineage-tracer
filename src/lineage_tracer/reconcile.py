"""Re-run what the scanner found, read-only, and compare it with the stored value.
A hop's `recon` spec: {kind: select|foreign|openlineage, target:{..}, value_col, filters, stored, select?, out_cols?, source?}."""

from __future__ import annotations

from psycopg import sql

from lineage_tracer.connectors import postgres, sqlite


def _f(x) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".") if x is not None else "n/a"


def _cmp(recalc, stored, tol: float, what: str) -> tuple[bool, str]:
    if recalc is None or stored is None:
        return False, f"Not reconciled: {what} returned no value"
    if abs(recalc - stored) <= tol:
        return True, f"Recalculated {_f(recalc)} agrees to stored value {_f(stored)} (tolerance ±{tol})"
    return False, f"Not reconciled: recalculated {_f(recalc)} vs stored {_f(stored)} (tolerance ±{tol})"


def check(spec: dict, connect, tol: float) -> tuple[str, str]:
    """-> (status, reconciliation text). `connect(ref)` returns an open connector connection or None."""
    kind, tgt, stored = spec.get("kind"), spec["target"], spec.get("stored")
    checks = spec.get("checks") or [[spec.get("value_col"), stored]]
    if all(x[1] is None for x in checks) and kind != "openlineage" or stored is None and kind != "select":
        return "code_derived", "Not reconciled: no numeric stored value for this attribute"
    try:
        if kind == "select":
            if tgt["type"] != "postgresql":
                return "code_derived", "Not reconciled: SELECT replay is only implemented for PostgreSQL"
            c = connect(tgt)
            if c is None:
                return "code_derived", "Not reconciled: no connection to the target system"
            types = dict(postgres.columns(c, tgt["schema"], tgt["table"]))
            w, p = postgres.where(spec["filters"], types)
            q = sql.SQL("SELECT ") + sql.SQL(", ").join(sql.SQL("count(*)") if x[0] == "*" else sql.SQL("sum({})").format(sql.Identifier(x[0])) for x in checks) +                 sql.SQL(" FROM (") + sql.SQL(spec["select"].replace("%", "%%")) +                 sql.SQL(") AS q ({}) WHERE ").format(sql.SQL(", ").join(sql.Identifier(x) for x in spec["out_cols"])) + w
            row = c.execute(q, p).fetchone()
            res = [_cmp(None if r is None else float(r), x[1], tol, "the discovered SELECT") + (x[0],) for r, x in zip(row, checks)]
            bad = next((r for r in res if not r[0]), None)
            r0 = bad or res[0]
            more = f" (+{len(res) - 1} more columns agree)" if not bad and len(res) > 1 else ""
            return ("code_derived" if bad else "proven"), f"{r0[1]} [{tgt['table']}.{'row count' if r0[2] == '*' else r0[2]}]{more}"
        if kind == "external":  # logic cannot be re-executed: reconcile by totals when it is identity / SUM / linear
            why = "pipeline logic not re-executable"
            f = spec.get("factor")
            if f is None:
                return "code_derived", f"Not reconciled: {why} (the column logic is not an identity, SUM or linear scaling)"
            src = spec["source"]
            c = connect(src)
            if c is None:
                return "code_derived", f"Not reconciled: {why}; no connection to {src['system']}"
            mod = postgres if src["type"] == "postgresql" else sqlite
            r = mod.sum_value(c, src["schema"], src["table"], spec["source_col"], spec["filters"])
            ok, msg = _cmp(None if r is None else r * f, stored, tol, f"{src['system']}.{src['table']}")
            basis = "identity" if f == 1 else f"× {f:g}"
            return ("proven" if ok else "code_derived"), f"{msg} · reconciled by totals ({basis}); {why}"
        if kind in ("foreign", "openlineage"):
            src = spec["source"]
            c = connect(src)
            if c is None:
                return "code_derived", f"Not reconciled: no connection to {src['system']}"
            mod = postgres if src["type"] == "postgresql" else sqlite
            r = mod.sum_value(c, src["schema"], src["table"], spec["source_col"], spec["filters"])
            ok, msg = _cmp(r, stored, tol, f"{src['system']}.{src['table']}")
            if kind == "openlineage":  # logic is inferred from lineage events, never 'proven'
                return "code_derived", msg + " (logic known from OpenLineage events only)"
            return ("proven" if ok else "code_derived"), msg
    except Exception as e:  # noqa: BLE001 - not executable is a reportable outcome, not a failure
        return "code_derived", f"Not reconciled: could not execute ({str(e).splitlines()[0][:140]})"
    return "code_derived", "Not reconciled: no executable logic"
