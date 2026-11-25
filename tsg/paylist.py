"""人件費支払一覧PDF: 実績と月末見込みを並べる
python3 -m tsg.paylist 実績CSV 見込みCSV 出力PDF 基準日"""
import sys
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from . import generate as G, rules as R


def calc(path):
    rows, notes = G.load(path)
    return rows, G.build_payroll(rows, notes), notes


def main(actual, forecast, out, asof):
    ra, pa, na = calc(actual)
    rf, pf, nf = calc(forecast)
    names = ["木ノ下"] + sorted(set(pa) | set(pf), key=lambda w: (w in R.NAKAGAWA_GUMI, w))
    hdr = ["作業員", "区分", "実績 日数", "実績 支払額", "見込 日数", "日当(+残業・税)", "交通費", "立替", "見込 支払額"]
    d = [hdr]; ta = tf = 0
    for w in names:
        if w == "木ノ下":
            da = sum(1 for r in ra if r["worker"] == w); df = sum(1 for r in rf if r["worker"] == w)
            d.append([w, "役員報酬", da, f"{R.OFFICER_PAY:,}", df, f"{R.OFFICER_PAY:,}", "0", "0", f"{R.OFFICER_PAY:,}"])
            ta += R.OFFICER_PAY; tf += R.OFFICER_PAY; continue
        a = pa.get(w); f = pf.get(w)
        kind = "外注(税込)" if w in R.NAKAGAWA_GUMI else ("給料+消費税" if w in R.TAXED_WORKERS else "給料")
        at = a["total"] if a else 0; ft = f["total"] if f else 0
        ta += at; tf += ft
        d.append([w if w != "中川組" else "中川組(メンバー未定)", kind, len(a["days"]) if a else 0, f"{int(at):,}",
                  len(f["days"]) if f else 0, f"{(f['wage'] + f['ot'] + f['tax']) if f else 0:,}",
                  f"{int(f['trav']) if f else 0:,}", f"{int(f['reimb']) if f else 0:,}", f"{int(ft):,}"])
    d.append(["合計", "", "", f"{int(ta):,}", "", "", "", "", f"{int(tf):,}"])
    t = Table(d, colWidths=[42 * mm, 26 * mm, 20 * mm, 30 * mm, 20 * mm, 30 * mm, 26 * mm, 20 * mm, 32 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), G.F, 9.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde3ea")),
                           ("ALIGN", (2, 1), (-1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), G.F, 11),
                           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eef7"))]))
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm)
    ym = ra[0]["date"]
    body = [Paragraph(f"人件費支払一覧　{ym:%Y年%m月}", G.ST["title"]), Paragraph(f"{asof}時点", G.ST["r"]), Spacer(0, 4 * mm), t,
            Spacer(0, 4 * mm), Paragraph("・実績＝終了報告分、見込＝実績＋スケジュール（月末まで）。交通費は20円/km、ETCは木ノ下カードのため含まず。", G.ST["n"])]
    body += [Paragraph("・" + x, G.ST["n"]) for x in dict.fromkeys(nf)]
    doc.build(body)
    return d


if __name__ == "__main__":
    for row in main(*sys.argv[1:5]):
        print("\t".join(str(x) for x in row))
