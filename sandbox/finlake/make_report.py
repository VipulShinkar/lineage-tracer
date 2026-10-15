"""EFR credit risk PDF, generated from rpt.v_efr_credit_risk_summary (same style as the C90 PDF)."""
from pathlib import Path

import psycopg
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "reports" / "efr_credit_risk_2026-06-30.pdf"
COLS = ["entity", "risk_type", "portfolio", "exposure_ead", "rwa", "expected_loss", "limit_amount", "utilisation_pct"]
with psycopg.connect("host=127.0.0.1 port=5433 user=lineage_ro password=lineage_ro dbname=fin_lake") as c:
    rows = c.execute(f"SELECT {', '.join(COLS)} FROM rpt.v_efr_credit_risk_summary").fetchall()

pdf = canvas.Canvas(str(OUT), pagesize=landscape(A4))
pdf.setTitle("EFR Credit Risk Summary")
w, h = landscape(A4)
y = h - 70
for line in ("EFR Credit Risk Summary;", "[LEGAL ENTITY] Group,", "Date : 30 Jun 2026", "Prepared under : BCBS 239 risk data aggregation"):
    pdf.setFont("Helvetica", 11)
    pdf.drawString(60, y, line)
    y -= 24
y -= 24
cx = [100, 170, 245, 335, 410, 495, 585, 675]  # column centres
pdf.setFont("Helvetica-Bold", 9)
for x, t in zip(cx, COLS):
    pdf.drawCentredString(x, y, t)
y -= 16
pdf.setFont("Helvetica", 9)
for r in rows:
    for i, (x, v) in enumerate(zip(cx, r)):
        pdf.drawCentredString(x, y, f"{v:.2f}" if i >= 3 else str(v))
    y -= 14
pdf.save()
print("wrote", OUT.name, len(rows), "rows")
