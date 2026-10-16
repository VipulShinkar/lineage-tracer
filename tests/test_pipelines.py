"""Query-history / csvlog / code-root / Informatica / Spark-SQL / totals units and the two known bug fixes (no sandbox needed)."""

import re
import textwrap

import psycopg

from lineage_tracer import pipelines as P
from lineage_tracer.connectors import postgres

CSV = ('2026-06-30 23:42:07.123 UTC,etl_owner,lcr_mart,11,[local],s1,1,INSERT,2026-06-30 23:40:00 UTC,3/4,0,LOG,00000,'
       '"statement: INSERT INTO core.fact_hqla SELECT a FROM stg.x WHERE d = \'2026-06-30\'",,,,,,,,,lcr_shell,client backend\n'
       '2026-06-30 23:42:09 UTC,etl_owner,lcr_mart,11,[local],s1,2,SELECT,2026-06-30 23:40:00 UTC,3/5,0,LOG,00000,'
       '"execute <unnamed>: INSERT INTO t VALUES ($1,$2)","parameters: $1 = \'x\', $2 = NULL",,,,,,,,pmdtm,client backend\n'
       '2026-06-30 23:42:10 UTC,u,lcr_mart,11,[local],s1,3,SELECT,2026-06-30 23:40:00 UTC,3/6,0,ERROR,42P01,"relation missing",,,,,,,,,psql,client backend\n')


def test_fingerprint_matches_across_sources():
    stat = "INSERT INTO core.fact_hqla SELECT a FROM stg.x WHERE d = $1 AND k IN ($2, $3)"
    log = "insert into core.fact_hqla\n  select a from stg.x -- c\n where d = '2026-06-30' and k in ('a','b');"
    assert P.fingerprint(stat) == P.fingerprint(log)
    assert P.fingerprint("select 1::numeric") != P.fingerprint("select 2::int")
    assert P.fingerprint("x = :'ent'") == P.fingerprint("x = $1")


def test_code_match_lines(tmp_path):
    f = tmp_path / "pipes" / "20_core.sql"
    f.parent.mkdir()
    f.write_text("DELETE FROM core.t;\n\n-- load\nINSERT INTO core.t (a)\nSELECT a FROM stg.t\nWHERE d = '2026-06-30';\n")
    assert P.code_match("INSERT INTO core.t (a) SELECT a FROM stg.t WHERE d = $1", [f.parent]) == "pipes/20_core.sql lines 3–6"
    assert P.code_match("INSERT INTO other SELECT 1", [f.parent]) is None


def test_csvlog_parse_and_format():
    e = P.parse_csvlog(CSV)
    assert len(e) == 2 and e[0]["app"] == "lcr_shell" and e[0]["user"] == "etl_owner" and e[0]["db"] == "lcr_mart"
    assert e[1]["sql"] == "INSERT INTO t VALUES ('x',NULL)"  # extended protocol parameters substituted
    assert P.fmt_log(e[0]).startswith("30-Jun 23:42:07 · app lcr_shell · user etl_owner · INSERT INTO core.fact_hqla")
    assert P.fingerprint(e[0]["sql"]).startswith("insert into core.fact_hqla select")


def test_connections_resolution(tmp_path):
    (tmp_path / "connections.xml").write_text('<CONNECTIONS><CONNECTION NAME="DWH" HOST="db1" PORT="5433" DBNAME="dwh_x"/></CONNECTIONS>')
    (tmp_path / "run.par").write_text("$DBConnection_stg = pg2:5440/staging_x\nrpt=postgresql://pg3/rpt_x\n")
    c = P.read_connections(tmp_path)
    assert c["DWH"] == {"host": "db1", "port": 5433, "database": "dwh_x"}
    assert c["stg"] == {"host": "pg2", "port": 5440, "database": "staging_x"} and c["rpt"]["port"] == 5432
    assert P.resolve_connection("dwh", c)["database"] == "dwh_x"
    assert P.resolve_connection("unknown_db", c) == {"host": "127.0.0.1", "port": 5432, "database": "unknown_db"}


MAPPING = textwrap.dedent("""\
<POWERMART><REPOSITORY><FOLDER NAME="F">
<SOURCE NAME="src_t" OWNERNAME="s1" DBDNAME="A"><SOURCEFIELD NAME="amt"/><SOURCEFIELD NAME="grp"/></SOURCE>
<TARGET NAME="tgt_t" OWNERNAME="s2" DBDNAME="B"><TARGETFIELD NAME="total"/><TARGETFIELD NAME="grp"/><TARGETFIELD NAME="flag"/></TARGET>
<MAPPING NAME="m_x">
 <TRANSFORMATION NAME="SQ" TYPE="Source Qualifier"><TRANSFORMFIELD NAME="amt" PORTTYPE="INPUT/OUTPUT" EXPRESSION=""/><TRANSFORMFIELD NAME="grp" PORTTYPE="INPUT/OUTPUT" EXPRESSION=""/></TRANSFORMATION>
 <TRANSFORMATION NAME="EXP" TYPE="Expression"><TRANSFORMFIELD NAME="amt" PORTTYPE="INPUT" EXPRESSION=""/><TRANSFORMFIELD NAME="grp" PORTTYPE="INPUT/OUTPUT" EXPRESSION="grp"/>
   <TRANSFORMFIELD NAME="flag" PORTTYPE="OUTPUT" EXPRESSION="IIF(amt &gt; 10, 'BIG', 'SMALL')"/><TRANSFORMFIELD NAME="amt2" PORTTYPE="OUTPUT" EXPRESSION="amt * 2"/></TRANSFORMATION>
 <TRANSFORMATION NAME="AGG" TYPE="Aggregator"><TRANSFORMFIELD NAME="grp" PORTTYPE="INPUT/OUTPUT" EXPRESSION="grp" EXPRESSIONTYPE="GROUPBY"/>
   <TRANSFORMFIELD NAME="in_amt" PORTTYPE="INPUT" EXPRESSION=""/><TRANSFORMFIELD NAME="total" PORTTYPE="OUTPUT" EXPRESSION="SUM(in_amt)"/><TRANSFORMFIELD NAME="flag" PORTTYPE="INPUT/OUTPUT" EXPRESSION="flag" EXPRESSIONTYPE="GROUPBY"/></TRANSFORMATION>
 <INSTANCE NAME="src_t" TYPE="SOURCE" TRANSFORMATION_NAME="src_t" DBDNAME="A"/><INSTANCE NAME="SQ" TRANSFORMATION_NAME="SQ" TRANSFORMATION_TYPE="Source Qualifier"/>
 <INSTANCE NAME="EXP" TRANSFORMATION_NAME="EXP" TRANSFORMATION_TYPE="Expression"/><INSTANCE NAME="AGG" TRANSFORMATION_NAME="AGG" TRANSFORMATION_TYPE="Aggregator"/>
 <INSTANCE NAME="tgt_t" TYPE="TARGET" TRANSFORMATION_NAME="tgt_t" DBDNAME="B"/>
 <CONNECTOR FROMINSTANCE="src_t" FROMFIELD="amt" TOINSTANCE="SQ" TOFIELD="amt"/><CONNECTOR FROMINSTANCE="src_t" FROMFIELD="grp" TOINSTANCE="SQ" TOFIELD="grp"/>
 <CONNECTOR FROMINSTANCE="SQ" FROMFIELD="amt" TOINSTANCE="EXP" TOFIELD="amt"/><CONNECTOR FROMINSTANCE="SQ" FROMFIELD="grp" TOINSTANCE="EXP" TOFIELD="grp"/>
 <CONNECTOR FROMINSTANCE="EXP" FROMFIELD="amt2" TOINSTANCE="AGG" TOFIELD="in_amt"/><CONNECTOR FROMINSTANCE="EXP" FROMFIELD="grp" TOINSTANCE="AGG" TOFIELD="grp"/>
 <CONNECTOR FROMINSTANCE="EXP" FROMFIELD="flag" TOINSTANCE="AGG" TOFIELD="flag"/>
 <CONNECTOR FROMINSTANCE="AGG" FROMFIELD="total" TOINSTANCE="tgt_t" TOFIELD="total"/><CONNECTOR FROMINSTANCE="AGG" FROMFIELD="grp" TOINSTANCE="tgt_t" TOFIELD="grp"/>
 <CONNECTOR FROMINSTANCE="AGG" FROMFIELD="flag" TOINSTANCE="tgt_t" TOFIELD="flag"/>
</MAPPING></FOLDER></REPOSITORY></POWERMART>""")


def test_informatica_mapping_job_lookup():
    conns = {"A": {"host": "h1", "port": 5432, "database": "dbA"}, "B": {"host": "h2", "port": 5433, "database": "dbB"}}
    (job,) = P.parse_mappings(MAPPING, conns)
    assert job["mapping"] == "m_x" and job["tables"] == ["dbB.s2.tgt_t"]
    by = {(e["target"][2], e["source"][2]): e for e in job["edges"]}
    t = by[("total", "amt")]
    assert t["source"][:2] == ("dbA.s1.src_t", "postgres://h1:5432") and t["target"][1] == "postgres://h2:5433"
    assert t["description"] == "SUM((amt * 2))" and t["subtype"] == "AGGREGATION" and t["type"] == "DIRECT"
    assert "EXP" in t["via"] and "AGG" in t["via"]
    assert by[("flag", "amt")]["description"].startswith("IIF(amt > 10")
    assert by[("grp", "grp")]["subtype"] == "IDENTITY"
    assert "If amt > 10 then 'BIG'" in P.rule_text(by[("flag", "amt")]["description"])
    assert "Aggregated (SUM)" in P.rule_text("SUM((amt * 2))")


def test_totals_factor():
    f = P.totals_factor
    assert f("DIRECT", "IDENTITY", None) == 1.0 and f("DIRECT", None, "ROUND(SUM(x) , 2)") == 1.0
    assert f("DIRECT", None, "x / 1000000") == 1e-6 and f("DIRECT", None, "ROUND(x * 100, 2)") == 100.0
    assert f("DIRECT", None, "a * b") is None and f("INDIRECT", "FILTER", "x") is None
    assert f("DIRECT", "AGGREGATION", None) == 1.0


def test_spark_sql_translation():
    sql = P.spark_insert('("core.f", """\nSELECT s.a, SUM(s.b) AS b FROM stg_loan s JOIN core_dim_x d ON d.k = s.k GROUP BY s.a""")',
                         "core", "f", ["raw", "stg", "core"])
    assert sql.startswith("INSERT INTO core.f SELECT") and "SUM(s.b)" in sql and "stg.loan" in sql and "core.dim_x" in sql


# ------------------------------------------------------------------ the two known bugs
class FakeConn:
    def __init__(self):
        self.q = []

    def execute(self, query, params=None):
        self.q.append((str(query), params))
        raise psycopg.Error("stop")


def test_log_evidence_accepts_only_executing_statements():
    c = FakeConn()
    postgres._log(c, "etl", "sp_x", "sp_x(")
    sql, params = c.q[0]
    assert "dbid" in sql and params[1] == postgres.STMT
    ok = re.compile(postgres.STMT, re.I | re.S)
    for good in ("CALL etl.sp_x()", "insert into a select 1", "UPDATE t SET a=1", "COPY t FROM STDIN", "SELECT a INTO b FROM c"):
        assert ok.match(good), good
    for bad in ("COMMENT ON PROCEDURE etl.sp_x() IS 'insert into a'", "SELECT * FROM t", "EXPLAIN INSERT INTO a SELECT 1"):
        assert not ok.match(bad), bad


def test_last_resort_lookup_is_database_scoped(monkeypatch):
    monkeypatch.setattr(P, "server_log", lambda conn: [])
    c = FakeConn()
    assert postgres._query_writers(c, "dbx", "s", "t", []) == []
    assert c.q and "pg_stat_statements" in c.q[0][0] and "dbid" in c.q[0][0]


def test_harvested_history_is_a_writer_and_log_literal_wins(monkeypatch):
    monkeypatch.setattr(P, "server_log", lambda conn: P.parse_csvlog(CSV))
    hist = [("INSERT INTO core.fact_hqla SELECT a FROM stg.x WHERE d = $1", 5), ("INSERT INTO other.t SELECT 1", 9)]
    (w,) = postgres._query_writers(FakeConn(), "lcr_mart", "core", "fact_hqla", hist)
    assert "'2026-06-30'" in w["sql"] and w["literal"] and w["log"].startswith("30-Jun 23:42:07 · app lcr_shell")
    (w2,) = postgres._query_writers(FakeConn(), "otherdb", "core", "fact_hqla", hist)  # the log of another database is ignored
    assert "$1" in w2["sql"] and not w2["literal"] and w2["log"].startswith("query history")


def test_openlineage_column_facet_and_mapping_ingest(conn):
    from lineage_store import db, ingest_ol
    from lineage_tracer.tracer import Tracer

    ev = {"eventTime": "2026-06-30T10:00:00Z", "producer": "https://github.com/OpenLineage/OpenLineage/tree/1.49.0/integration/spark",
          "run": {"runId": "r-ol-1"}, "job": {"name": "app.save.rpt_t", "facets": {"sourceCodeLocation": {"path": "pipelines/spark/job.py"}}},
          "outputs": [{"namespace": "postgres://127.0.0.1:5433", "name": "dbz.rpt.t", "facets": {"columnLineage": {"fields": {
              "total": {"inputFields": [{"namespace": "postgres://127.0.0.1:5433", "name": "dbz.core.f", "field": "amt",
                                         "transformations": [{"type": "DIRECT", "subtype": "AGGREGATION", "description": "SUM(amt)"}]}]}}}}}]}
    ingest_ol.ingest_event(conn, ev)
    r = db.cypher(conn, "MATCH (s:Field)-[e:DERIVES]->(t:Field {uid: 'field:dbz.rpt.t.total'}) RETURN s.uid, e.subtype, e.description, e.producer, e.code_loc", cols=5)
    assert r == [("field:dbz.core.f.amt", "AGGREGATION", "SUM(amt)", ev["producer"], "pipelines/spark/job.py")]
    assert Tracer.ds_match("dbz.rpt.t", {"type": "postgresql", "database": "dbz", "schema": "rpt", "table": "t"})
    assert not Tracer.ds_match("dbz.rpt.t", {"type": "postgresql", "database": "dbz", "schema": "core", "table": "t"})
    # a PowerCenter mapping becomes the same kind of job; quotes in expressions survive the Cypher literal
    n = ingest_ol.ingest_job(conn, "m_unit", "informatica", "informatica/m_unit.xml", [{
        "target": ("dby.s.t", "postgres://h:5432", "flag"), "source": ("dby.s.src", "postgres://h:5432", "amt"), "type": "DIRECT",
        "subtype": "TRANSFORMATION", "description": "IIF(amt > 10, 'BIG', 'SMALL')", "via": "EXP"}])
    assert n >= 1
    (row,) = db.cypher(conn, "MATCH ()-[e:DERIVES {job_id: 'job:m_unit'}]->() RETURN e.description", cols=1)
    assert row == "IIF(amt > 10, 'BIG', 'SMALL')"
