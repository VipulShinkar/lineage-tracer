"""Writes the 4 C90 PowerCenter mapping exports + connections.xml (run once; output is committed)."""
from pathlib import Path

from lxml import etree

OUT = Path(__file__).resolve().parent
S, D, T = "string", "decimal", "date/time"
SENS = [("trade_id", S, 255, 0), ("book", S, 255, 0), ("desk", S, 255, 0), ("consolidation_group", S, 255, 0),
        ("risk_class", S, 255, 0), ("sensitivity_type", S, 255, 0), ("risk_factor", S, 255, 0), ("currency", S, 3, 0),
        ("sensitivity_amount", D, 20, 4), ("as_of_date", T, 29, 9)]
SENS_USD = [SENS[0], SENS[3], SENS[4], SENS[5], SENS[6], SENS[7], SENS[8], ("fx_rate_to_usd", D, 18, 8),
            ("sensitivity_usd", D, 20, 6), SENS[9]]
FX = [("ccy", S, 3, 0), ("rate_date", T, 29, 9), ("rate_to_eur", D, 18, 8), ("rate_to_usd", D, 18, 8)]
RW = [("risk_class", S, 255, 0), ("sensitivity_type", S, 255, 0), ("risk_weight", D, 9, 6)]
SBM = [("consolidation_group", S, 255, 0), ("risk_class", S, 255, 0), ("sensitivity_type", S, 255, 0),
       ("sensitivity_usd_total", D, 20, 6), ("risk_weight", D, 9, 6), ("sbm_charge_usd", D, 20, 2), ("as_of_date", T, 29, 9)]
FACTS = [("consolidation_group", S, 255, 0), ("risk_class", S, 255, 0), ("sensitivity_type", S, 255, 0),
         ("reported_value_usd", D, 18, 2), ("as_of_date", T, 29, 9)]
CONNS = ["trading_db", "staging", "dwh", "frtb_engine", "reporting_db"]


def el(parent, tag, **a):
    return etree.SubElement(parent, tag, {k: str(v) for k, v in a.items()})


def fld(parent, tag, c, **extra):
    n, dt, p, s = c
    return el(parent, tag, NAME=n, DATATYPE=dt, PRECISION=p, SCALE=s, **extra)


def table_def(folder, tag, conn, schema, name, cols):
    t = el(folder, tag, NAME=name, OWNERNAME=schema, DATABASETYPE="PostgreSQL", DBDNAME=conn, BUSINESSNAME="", DESCRIPTION="")
    for i, c in enumerate(cols, 1):
        fld(t, "SOURCEFIELD" if tag == "SOURCE" else "TARGETFIELD", c, FIELDNUMBER=i, KEYTYPE="NOT A KEY", NULLABLE="NULL")


def P(name, dt, prec, scale, ptype, expr=None, etype="GENERAL"):
    return dict(n=name, c=(name, dt, prec, scale), pt=ptype, e=expr or name, et=etype)


def passthru(cols):
    return [P(*c, "INPUT/OUTPUT") for c in cols]


def build(fname, mname, src, tgt, txs, lookup_srcs=()):
    """src/tgt = (conn, schema, table, cols). txs = [(name, type, ports, attrs, upstream_instance, port_link_overrides)]."""
    pm = etree.Element("POWERMART", CREATION_DATE="10/16/2026 09:00:00", REPOSITORY_VERSION="186.95")
    rep = el(pm, "REPOSITORY", NAME="REP_C90", VERSION="186", CODEPAGE="UTF-8", DATABASETYPE="Oracle")
    f = el(rep, "FOLDER", NAME="COREP_C90", GROUP="", OWNER="Administrator", SHARED="NOTSHARED",
           DESCRIPTION="COREP C90 FRTB SBM loads", PERMISSIONS="rwx---r--")
    table_def(f, "SOURCE", *src)
    for ls in lookup_srcs:
        table_def(f, "SOURCE", *ls)
    table_def(f, "TARGET", *tgt)
    m = el(f, "MAPPING", NAME=mname, DESCRIPTION="", ISVALID="YES", OBJECTVERSION="1", VERSIONNUMBER="1")
    sq = "SQ_" + src[2]
    t = el(m, "TRANSFORMATION", NAME=sq, TYPE="Source Qualifier", REUSABLE="NO", DESCRIPTION="", OBJECTVERSION="1", VERSIONNUMBER="1")
    for c in src[3]:
        fld(t, "TRANSFORMFIELD", c, PORTTYPE="INPUT/OUTPUT", DEFAULTVALUE="", EXPRESSION="", EXPRESSIONTYPE="GENERAL")
    for k, v in (("Sql Query", ""), ("User Defined Join", ""), ("Source Filter", ""), ("Number Of Sorted Ports", "0"),
                 ("Tracing Level", "Normal"), ("Select Distinct", "NO")):
        el(t, "TABLEATTRIBUTE", NAME=k, VALUE=v)
    for name, typ, ports, attrs, up, links in txs:
        t = el(m, "TRANSFORMATION", NAME=name, TYPE=typ, REUSABLE="NO", DESCRIPTION="", OBJECTVERSION="1", VERSIONNUMBER="1")
        for p in ports:
            fld(t, "TRANSFORMFIELD", p["c"], PORTTYPE=p["pt"], DEFAULTVALUE="",
                EXPRESSION=p["e"] if "OUTPUT" in p["pt"] else "", EXPRESSIONTYPE=p["et"])
        for k, v in attrs.items():
            el(t, "TABLEATTRIBUTE", NAME=k, VALUE=v)
    el(m, "INSTANCE", NAME=src[2], TYPE="SOURCE", TRANSFORMATION_NAME=src[2], TRANSFORMATION_TYPE="Source Definition", DBDNAME=src[0])
    i = el(m, "INSTANCE", NAME=sq, TRANSFORMATION_NAME=sq, TRANSFORMATION_TYPE="Source Qualifier", REUSABLE="NO")
    el(i, "ASSOCIATED_SOURCE_INSTANCE", NAME=src[2])
    for ls in lookup_srcs:  # lookup table as a source-definition instance feeding the lookup's return ports
        el(m, "INSTANCE", NAME=ls[2], TYPE="SOURCE", TRANSFORMATION_NAME=ls[2], TRANSFORMATION_TYPE="Source Definition", DBDNAME=ls[0])
    for name, typ, *_ in txs:
        el(m, "INSTANCE", NAME=name, TRANSFORMATION_NAME=name, TRANSFORMATION_TYPE=typ, REUSABLE="NO")
    el(m, "INSTANCE", NAME=tgt[2], TYPE="TARGET", TRANSFORMATION_NAME=tgt[2], TRANSFORMATION_TYPE="Target Definition", DBDNAME=tgt[0])

    def con(a, af, b, bf):
        el(m, "CONNECTOR", FROMINSTANCE=a, FROMFIELD=af, TOINSTANCE=b, TOFIELD=bf, FROMINSTANCETYPE="", TOINSTANCETYPE="")

    for c in src[3]:
        con(src[2], c[0], sq, c[0])
    for name, typ, ports, attrs, up, links in txs:
        for p in ports:
            if "INPUT" in p["pt"]:
                a, af = links.get(p["n"], (up, p["n"]))
                con(a, af, name, p["n"])
        for ls in lookup_srcs:
            if typ == "Lookup Procedure" and attrs.get("Lookup table name") == ls[2]:
                for p in ports:
                    if p["pt"] == "LOOKUP/OUTPUT":
                        con(ls[2], p["n"], name, p["n"])
    last = txs[-1][0] if txs else sq
    for c in tgt[3]:
        con(last, c[0], tgt[2], c[0])
    el(m, "TARGETLOADORDER", ORDER=1, TARGETINSTANCE=tgt[2])
    s = el(f, "SESSION", NAME="s_" + mname, MAPPINGNAME=mname, DESCRIPTION="", ISVALID="YES", REUSABLE="NO", VERSIONNUMBER="1")
    for inst, conn, kind in [(sq, src[0], "Source")] + [(x[2], x[0], "Source") for x in lookup_srcs] + [(tgt[2], tgt[0], "Target")]:
        ti = el(s, "SESSTRANSFORMATIONINST", SINSTANCENAME=inst, TRANSFORMATIONNAME=inst, PIPELINE=0, STAGE=1,
                TRANSFORMATIONTYPE="Source Qualifier" if kind == "Source" else "Target Definition")
        el(ti, "CONNECTIONREFERENCE", CONNECTIONNAME=conn, CONNECTIONTYPE="Relational", CONNECTIONSUBTYPE="PostgreSQL", VARIABLE="")
    el(s, "ATTRIBUTE", NAME="Treat source rows as", VALUE="Insert")
    el(s, "ATTRIBUTE", NAME="Truncate target table option", VALUE="NO")
    w = el(f, "WORKFLOW", NAME="wf_" + mname, DESCRIPTION="", ISVALID="YES", REUSABLE="NO", SERVERNAME="IS_C90", VERSIONNUMBER="1")
    el(w, "TASKINSTANCE", NAME="s_" + mname, TASKNAME="s_" + mname, TASKTYPE="Session", REUSABLE="NO")
    etree.ElementTree(pm).write(str(OUT / fname), pretty_print=True, xml_declaration=True, encoding="UTF-8")


def m1():
    build("m_C90_stg_sensitivity.xml", "m_C90_stg_sensitivity", ("trading_db", "trd", "trade_sensitivity", SENS),
          ("staging", "public", "stg_sensitivity", SENS), [])


def m2():
    lkp = [P("in_currency", S, 3, 0, "INPUT"), P("in_as_of_date", T, 29, 9, "INPUT"),
           P("ccy", S, 3, 0, "LOOKUP/OUTPUT"), P("rate_date", T, 29, 9, "LOOKUP/OUTPUT"), P("rate_to_usd", D, 18, 8, "LOOKUP/OUTPUT")]
    fil = passthru(SENS) + [P("rate_to_usd", D, 18, 8, "INPUT/OUTPUT")]
    keep = [c for c in SENS if c[0] not in ("book", "desk", "as_of_date")]
    exp = [P(*c, "INPUT/OUTPUT") for c in keep] + [
        P("rate_to_usd", D, 18, 8, "INPUT"),
        P("fx_rate_to_usd", D, 18, 8, "OUTPUT", "rate_to_usd"),
        P("sensitivity_usd", D, 20, 6, "OUTPUT", "ROUND(sensitivity_amount * rate_to_usd, 6)"),
        P("as_of_date", T, 29, 9, "INPUT/OUTPUT")]
    sq = "SQ_stg_sensitivity"
    build("m_C90_dw_sensitivity_usd.xml", "m_C90_dw_sensitivity_usd", ("staging", "public", "stg_sensitivity", SENS),
          ("dwh", "public", "dw_sensitivity_usd", SENS_USD), [
              ("LKP_FX_RATE", "Lookup Procedure", lkp,
               {"Lookup table name": "ref_fx_rates", "Lookup condition": "ccy = in_currency AND rate_date = in_as_of_date",
                "Lookup source filter": "", "Connection Information": "staging", "Lookup policy on multiple match": "Use First Value"},
               sq, {"in_currency": (sq, "currency"), "in_as_of_date": (sq, "as_of_date")}),
              ("FIL_FX_FOUND", "Filter", fil, {"Filter Condition": "NOT ISNULL(rate_to_usd)"}, sq, {"rate_to_usd": ("LKP_FX_RATE", "rate_to_usd")}),
              ("EXP_SENSITIVITY_USD", "Expression", exp, {}, "FIL_FX_FOUND", {}),
          ], lookup_srcs=[("staging", "public", "ref_fx_rates", FX)])


def m3():
    lkp = [P("in_risk_class", S, 255, 0, "INPUT"), P("in_sensitivity_type", S, 255, 0, "INPUT"),
           P("risk_class", S, 255, 0, "LOOKUP/OUTPUT"), P("sensitivity_type", S, 255, 0, "LOOKUP/OUTPUT"),
           P("risk_weight", D, 9, 6, "LOOKUP/OUTPUT")]
    base = [P("consolidation_group", S, 255, 0, "INPUT/OUTPUT"), P("risk_class", S, 255, 0, "INPUT/OUTPUT"),
            P("sensitivity_type", S, 255, 0, "INPUT/OUTPUT"), P("sensitivity_usd", D, 20, 6, "INPUT/OUTPUT"),
            P("as_of_date", T, 29, 9, "INPUT/OUTPUT"), P("risk_weight", D, 9, 6, "INPUT/OUTPUT")]
    exp = base + [P("weighted_usd", D, 28, 12, "OUTPUT", "sensitivity_usd * risk_weight")]
    agg = [P("consolidation_group", S, 255, 0, "INPUT/OUTPUT", etype="GROUPBY"), P("risk_class", S, 255, 0, "INPUT/OUTPUT", etype="GROUPBY"),
           P("sensitivity_type", S, 255, 0, "INPUT/OUTPUT", etype="GROUPBY"), P("risk_weight", D, 9, 6, "INPUT/OUTPUT", etype="GROUPBY"),
           P("in_sensitivity_usd", D, 20, 6, "INPUT"), P("in_weighted_usd", D, 28, 12, "INPUT"), P("in_as_of_date", T, 29, 9, "INPUT"),
           P("sensitivity_usd_total", D, 20, 6, "OUTPUT", "SUM(in_sensitivity_usd)"),
           P("sbm_charge_usd", D, 20, 2, "OUTPUT", "ROUND(SUM(in_weighted_usd), 2)"),
           P("as_of_date", T, 29, 9, "OUTPUT", "MAX(in_as_of_date)")]
    sq = "SQ_dw_sensitivity_usd"
    build("m_C90_calc_sbm_charge.xml", "m_C90_calc_sbm_charge", ("dwh", "public", "dw_sensitivity_usd", SENS_USD),
          ("frtb_engine", "public", "calc_sbm_charge", SBM), [
              ("LKP_RISK_WEIGHT", "Lookup Procedure", lkp,
               {"Lookup table name": "ref_risk_weight", "Lookup condition": "risk_class = in_risk_class AND sensitivity_type = in_sensitivity_type",
                "Lookup source filter": "", "Connection Information": "frtb_engine", "Lookup policy on multiple match": "Use First Value"},
               sq, {"in_risk_class": (sq, "risk_class"), "in_sensitivity_type": (sq, "sensitivity_type")}),
              ("FIL_RW_FOUND", "Filter", base, {"Filter Condition": "NOT ISNULL(risk_weight)"}, sq, {"risk_weight": ("LKP_RISK_WEIGHT", "risk_weight")}),
              ("EXP_WEIGHTED", "Expression", exp, {}, "FIL_RW_FOUND", {}),
              ("AGG_SBM", "Aggregator", agg, {"Sorted Input": "NO"}, "EXP_WEIGHTED",
               {"in_sensitivity_usd": ("EXP_WEIGHTED", "sensitivity_usd"), "in_weighted_usd": ("EXP_WEIGHTED", "weighted_usd"),
                "in_as_of_date": ("EXP_WEIGHTED", "as_of_date")}),
          ], lookup_srcs=[("frtb_engine", "public", "ref_risk_weight", RW)])


def m4():
    exp = [P("consolidation_group", S, 255, 0, "INPUT/OUTPUT"), P("risk_class", S, 255, 0, "INPUT/OUTPUT"),
           P("sensitivity_type", S, 255, 0, "INPUT/OUTPUT"), P("sbm_charge_usd", D, 20, 2, "INPUT"),
           P("reported_value_usd", D, 18, 2, "OUTPUT", "sbm_charge_usd"), P("as_of_date", T, 29, 9, "INPUT/OUTPUT")]
    build("m_C90_rpt_c90_facts.xml", "m_C90_rpt_c90_facts", ("frtb_engine", "public", "calc_sbm_charge", SBM),
          ("reporting_db", "rpt", "c90_facts", FACTS), [("EXP_REPORTED_VALUE", "Expression", exp, {}, "SQ_calc_sbm_charge", {})])


def connections():
    r = etree.Element("CONNECTIONS", DESCRIPTION="PowerCenter relational connection objects (sandbox credentials)")
    for n in CONNS:
        el(r, "CONNECTION", NAME=n, TYPE="Relational", SUBTYPE="PostgreSQL", HOST="127.0.0.1", PORT=5432, DBNAME=n,
           USER="etl_owner", PASSWORD="etl_owner")
    etree.ElementTree(r).write(str(OUT / "connections.xml"), pretty_print=True, xml_declaration=True, encoding="UTF-8")


if __name__ == "__main__":
    m1(); m2(); m3(); m4(); connections()
