"""LCR liquidity PDF, generated from rpt.v_lcr_summary (same style as the EFR / C90 PDFs)."""
from pathlib import Path

import psycopg
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[2] / "reports" / "lcr_liquidity_2026-06-30.pdf"
COLS = ["entity", "hqla_usd", "outflows_usd", "inflows_usd", "net_outflows_usd", "lcr_pct"]
with psycopg.connect("host=127.0.0.1 port=5432 user=lineage_ro password=lineage_ro dbname=lcr_mart") as c:
    rows = c.execute(f"SELECT {', '.join(COLS)} FROM rpt.v_lcr_summary ORDER BY entity = 'GROUP', entity").fetchall()

pdf = canvas.Canvas(str(OUT), pagesize=landscape(A4))
pdf.setTitle("LCR Liquidity Coverage")
w, h = landscape(A4)
y = h - 70
for line in ("LCR Liquidity Coverage;", "[LEGAL ENTITY] Group,", "Date : 30 Jun 2026", "Prepared under : Basel III LCR (amounts in USD m)"):
    pdf.setFont("Helvetica", 11)
    pdf.drawString(60, y, line)
    y -= 24
y -= 24
cx = [100, 210, 320, 430, 540, 650]
pdf.setFont("Helvetica-Bold", 9)
for x, t in zip(cx, COLS):
    pdf.drawCentredString(x, y, t)
y -= 16
pdf.setFont("Helvetica", 9)
for r in rows:
    for i, (x, v) in enumerate(zip(cx, r)):
        pdf.drawCentredString(x, y, f"{v:.2f}" if i >= 1 else str(v))
    y -= 14
pdf.save()
print("wrote", OUT.name, len(rows), "rows")
