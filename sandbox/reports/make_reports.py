"""Generates the two report files a user would upload: C90 PDF and C 07.00 XBRL-style instance.
Values are read from reporting_db (so they always equal what Superset shows)."""
from pathlib import Path

import psycopg
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent
DSN = "host=127.0.0.1 port=5432 user=lineage_ro password=lineage_ro dbname=reporting_db"
ENTITY = "[LEGAL ENTITY]"

with psycopg.connect(DSN) as c:
    c90 = c.execute("SELECT consolidation_group, risk_class, sensitivity_type, reported_value_usd FROM rpt.v_corep_c90").fetchall()
    c07 = c.execute("SELECT row_code, col_code, value FROM rpt.c0700_facts WHERE sheet='Corporates' ORDER BY 1,2").fetchall()

# ---- C90 PDF (layout of the user's report)
pdf = canvas.Canvas(str(OUT / "corep_c90_2026-06-30.pdf"), pagesize=A4)
pdf.setTitle("COREP C90 Report")
w, h = A4
y = h - 90
for line in ("COREP C90 Report;", f"{ENTITY},", "Date : 30 Jun 2026", "Delivered to : Prudential Regulatory Authority"):
    pdf.setFont("Helvetica", 11)
    pdf.drawString(80, y, line)
    y -= 26
y -= 30
xs = [95, 215, 290, 400]  # left edge of each column; values are centred like the original
heads = ["consolidation_group", "risk_class", "sensitivity_type", "reported_value_usd"]
pdf.setFont("Helvetica-Bold", 9)
for x, t in zip(xs, heads):
    pdf.drawString(x, y, t)
y -= 16
pdf.setFont("Helvetica", 9)
for g, rc, st, v in c90:
    for x, t, wd in zip(xs, (g, rc, st, f"{v:.2f}"), (80, 60, 85, 90)):
        pdf.drawCentredString(x + {0: 40, 1: 25, 2: 40, 3: 45}[xs.index(x)], y, t)
    y -= 14
pdf.save()

# ---- XBRL-style instance (simplified, parseable)
ctx, facts = [], []
for r, col, v in c07:
    cid = f"c_C0700_Corporates_r{r}_c{col}"
    ctx.append(f"""  <xbrli:context id="{cid}">
    <xbrli:entity><xbrli:identifier scheme="urn:sandbox:placeholder">{ENTITY}</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="dim:Template">tpl:C0700</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="dim:Sheet">sheet:Corporates</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="dim:Row">row:r{r}</xbrldi:explicitMember>
        <xbrldi:explicitMember dimension="dim:Column">col:c{col}</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>""")
    facts.append(f'  <corep:ExposureValue contextRef="{cid}" unitRef="EURm" decimals="1">{v}</corep:ExposureValue>')
xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- COREP C 07.00 (Credit risk SA) - Corporates - reference date 2026-06-30 - submission version v1 - consolidation Solo -->
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:corep="urn:sandbox:corep" xmlns:dim="urn:sandbox:dim" xmlns:tpl="urn:sandbox:tpl"
            xmlns:sheet="urn:sandbox:sheet" xmlns:row="urn:sandbox:row" xmlns:col="urn:sandbox:col"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <corep:ReportingEntity>{ENTITY}</corep:ReportingEntity>
  <corep:ReportingReferenceDate>2026-06-30</corep:ReportingReferenceDate>
  <corep:SubmissionVersion>v1</corep:SubmissionVersion>
  <corep:ConsolidationBasis>Solo</corep:ConsolidationBasis>
  <xbrli:unit id="EURm"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
{chr(10).join(ctx)}
{chr(10).join(facts)}
</xbrli:xbrl>
"""
(OUT / "corep_2026-06-30_v1.xbrl").write_text(xml, encoding="utf-8")
print("wrote reports:", len(c90), "c90 rows,", len(c07), "xbrl facts")
