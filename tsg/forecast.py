"""売上見込みPDF: python3 -m tsg.forecast 見込みCSV(実績＋予定) 出力PDF 基準日"""
import sys
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from . import generate as G


def main(src, out, asof, notes_extra=()):
    rows, notes = G.load(src)
    inv = G.build_invoices(rows, notes)
    d = [["取引先", "人工", "人工代", "交通費", "消費税", "請求額(税込)"]]
    keys = ("labor", "nontax_total", "tax", "total")
    for c in sorted(inv, key=lambda c: -inv[c]["total"]):
        i = inv[c]
        d.append([G.R.OFFICIAL.get(c, c), sum(v[0] for v in i["lines"].values())]
                 + [f"{int(i[k]):,}" for k in keys])
    ex = sum(i["sales_ex"] for i in inv.values()); tt = sum(i["total"] for i in inv.values())
    d.append(["合計見込み", sum(r[1] for r in d[1:])]
             + [f"{int(sum(i[k] for i in inv.values())):,}" for k in keys])
    t = Table(d, colWidths=[52 * mm, 14 * mm, 28 * mm, 25 * mm, 25 * mm, 30 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), G.F, 9.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde3ea")),
                           ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), G.F, 11),
                           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eef7"))]))
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm)
    body = [Paragraph(f"売上見込み　{rows[0]['date']:%Y年%m月}", G.ST["title"]), Paragraph(f"{asof}時点", G.ST["r"]),
            Spacer(0, 5 * mm), t, Spacer(0, 5 * mm), Paragraph("前提・確認事項", G.ST["h"])]
    body += [Paragraph("・" + x, G.ST["n"]) for x in list(notes_extra) + list(dict.fromkeys(notes))]
    doc.build(body)
    return inv, ex, tt


if __name__ == "__main__":
    main(*sys.argv[1:4])
