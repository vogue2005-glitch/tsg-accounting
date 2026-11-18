"""終了報告CSV → 請求書PDF / 給料明細PDF / 月次サマリーPDF

使い方: python3 -m tsg.generate data/2026-11.csv
CSV列: 日付,取引先,現場,作業員,昼夜,休日,距離km,ETC,駐車場,燃料,宿泊,残業h,備考[,請求単価,本人立替]
  本人立替: 作業員本人が立て替えたETC等（給料で精算。ETC列にも同額を入れて請求する）
  請求単価: 例 7500税込 / 20000（税抜）。中川案件など案件ごとに単価が違う場合に指定（空欄=ルール単価）
  昼夜: 夜/空欄(=昼。夜勤の記載がなければ昼)   休日: 空欄=自動判定(土日祝) / 1=休日 / 0=平日
  距離km: 運転者の行のみ記載（空欄=乗り合い→0円）
"""
import calendar
import csv
import datetime as dt
import math
import sys
from collections import defaultdict, OrderedDict
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Table, TableStyle,
                                Spacer, PageBreak)

from . import rules as R

pdfmetrics.registerFont(TTFont("IPAGothic", "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"))
F = "IPAGothic"
ST = {k: ParagraphStyle(k, fontName=F, fontSize=s, leading=s * 1.4, alignment=a)
      for k, s, a in [("title", 20, 1), ("h", 12, 0), ("n", 9.5, 0), ("r", 9.5, 2),
                      ("big", 16, 0), ("s", 8, 0)]}


def yen(v):
    return f"¥{int(round(v)):,}"


def num(s):
    s = (s or "").replace(",", "").replace("円", "").replace("km", "").strip()
    return float(s) if s else 0.0


def parse_date(s):
    s = s.strip().replace("/", "-").replace(".", "-")
    return dt.date.fromisoformat("-".join(p.zfill(2) for p in s.split("-")))


def load(path):
    rows, notes = [], []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not (r.get("日付") or "").strip():
                continue
            d = parse_date(r["日付"])
            client = R.CLIENT_ALIAS.get(r["取引先"].strip(), r["取引先"].strip())
            worker = r["作業員"].strip()
            worker = R.WORKER_ALIAS.get(worker, worker)
            shift = (r.get("昼夜") or "").strip()
            if shift not in ("昼", "夜"):  # 終了報告に「夜勤」の記載がなければ昼
                shift = "昼"
            hol = (r.get("休日") or "").strip()
            holiday = R.is_holiday(d) if hol == "" else hol == "1"
            rows.append(dict(date=d, client=client, site=(r.get("現場") or "").strip(),
                             worker=worker, night=shift == "夜", holiday=holiday,
                             km=num(r.get("距離km")), etc=num(r.get("ETC")),
                             parking=num(r.get("駐車場")), fuel=num(r.get("燃料")),
                             lodging=num(r.get("宿泊")), ot=num(r.get("残業h")),
                             bill_rate=num((r.get("請求単価") or "").replace("税込", "").replace("税抜", "")),
                             bill_incl="込" in (r.get("請求単価") or ""),
                             reimb=num(r.get("本人立替")),
                             memo=(r.get("備考") or "").strip()))
    for r in rows:  # 備考に「後日」「要確認」があれば確認事項に残す
        if "後日" in r["memo"] or "要確認" in r["memo"]:
            notes.append(f"{r['date']:%m/%d} {r['client']} {r['worker']}: {r['memo']}")
    return rows, notes


# ---------------- 請求 ----------------
def build_invoices(rows, notes):
    inv = OrderedDict()
    for r in sorted(rows, key=lambda x: (x["client"], x["date"], x["site"])):
        c = r["client"]
        rate, incl, ot_rate, travel, lab = R.bill_rule(c, r["site"], r["night"], r["holiday"],
                                                       [] if r["bill_rate"] else notes)
        if r["bill_rate"]:  # 個別指定単価（中川案件など）を優先。「7500税込」で税込指定
            rate = int(r["bill_rate"])
            incl = r["bill_incl"]
        i = inv.setdefault(c, dict(lines=defaultdict(lambda: [0, 0]), ot=defaultdict(float),
                                   km=0, etc=0, receipt=0, lodging=0, incl=incl, lab=lab,
                                   travel=travel, ot_rate=ot_rate))
        i["incl"] = incl
        label = "夜勤" if r["night"] else ("休日" if r["holiday"] and rate >= 25_000 and c not in ("メンテック", "アスカ技建") else "")
        i["lines"][(r["date"], r["site"], label, rate)][0] += 1
        if r["ot"]:
            if ot_rate:
                i["ot"][(r["date"], r["site"])] += r["ot"]
            else:
                notes.append(f"{r['date']:%m/%d} {c}: 残業{r['ot']}h → 請求しないルールのため除外")
        if travel == "km":
            i["km"] += r["km"]
            i["etc"] += r["etc"]
            i["receipt"] += r["parking"] + r["fuel"]
            if r["parking"] or r["fuel"]:
                notes.append(f"{r['date']:%m/%d} {c}: 駐車場/燃料 実費を立替として請求計上（要確認）")
        elif travel == "receipt":
            i["receipt"] += r["etc"] + r["parking"] + r["fuel"]
        else:
            if r["km"] or r["etc"]:
                notes.append(f"{r['date']:%m/%d} {c}: 交通費/ETCは請求しないルールのため除外")
        if r["lodging"]:
            i["lodging"] += r["lodging"]
            notes.append(f"{r['date']:%m/%d} {c}: 宿泊費{yen(r['lodging'])}を実費請求で仮計上（要確認）")

    for c, i in inv.items():
        items, labor = [], 0
        for (d, site, label, rate), (n, _) in sorted(i["lines"].items()):
            amt = n * rate
            labor += amt
            items.append([f"{d.month}/{d.day}", site + (f"（{label}）" if label else ""), n, rate, amt])
        for (d, site), h in sorted(i["ot"].items()):
            amt = round(h * i["ot_rate"])
            labor += amt
            items.append([f"{d.month}/{d.day}", f"{site} 残業 {h:g}h", "", round(i["ot_rate"]), amt])
        if i["lab"]:
            la = round(labor * i["lab"])
            items.append(["", f"労務費（人工代の{int(i['lab']*100)}%）", "", "", la])
            labor += la
        if i["incl"]:
            tax = math.floor(labor * 10 / 110)
            taxable_ex = labor - tax
        else:
            tax = math.floor(labor * R.TAX)
            taxable_ex = labor
        nontax = []
        if i["km"]:
            nontax.append(["", f"交通費 {i['km']:g}km × {R.BILL_KM}円", "", R.BILL_KM, i["km"] * R.BILL_KM])
        if i["etc"]:
            nontax.append(["", "ETC（実費）", "", "", i["etc"]])
        if i["receipt"]:
            nontax.append(["", "交通費等 実費（領収書）", "", "", i["receipt"]])
        if i["lodging"]:
            nontax.append(["", "宿泊費（実費）", "", "", i["lodging"]])
        nontax_total = sum(x[4] for x in nontax)
        i.update(items=items, nontax=nontax, labor=labor, tax=tax,
                 sales_ex=taxable_ex + nontax_total,
                 total=(labor if i["incl"] else labor + tax) + nontax_total,
                 nontax_total=nontax_total)
    return inv


def invoice_pdf(path, client, i, ym, inv_no, issue, due):
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    addr = R.ADDRESSES.get(client, "（住所：過去スレ参照・要確認）")
    s = [Paragraph("請 求 書", ST["title"]), Spacer(0, 6 * mm)]
    left = [Paragraph(addr, ST["n"]), Paragraph(f"<font size=14>{client}　御中</font>", ST["h"]),
            Spacer(0, 3 * mm), Paragraph(f"件名：{ym.year}年{ym.month}月分 作業代", ST["n"])]
    right = [Paragraph(f"請求番号：{inv_no}", ST["r"]), Paragraph(f"請求日：{issue:%Y年%m月%d日}", ST["r"]),
             Spacer(0, 2 * mm), Paragraph(R.ISSUER["name"], ST["r"]), Paragraph(R.ISSUER["rep"], ST["r"]),
             Paragraph(f"{R.ISSUER['zip']} {R.ISSUER['addr']}", ST["s"]),
             Paragraph(R.ISSUER["tel"], ST["r"]), Paragraph(R.ISSUER["reg"], ST["r"])]
    t = Table([[left, right]], colWidths=[90 * mm, 84 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    s += [t, Spacer(0, 5 * mm), Paragraph("下記の通りご請求申し上げます。", ST["n"]), Spacer(0, 2 * mm)]
    amt = Table([[Paragraph("ご請求金額（税込）", ST["h"]), Paragraph(f"<b>{yen(i['total'])}</b>", ST["big"])]],
                colWidths=[50 * mm, 70 * mm], rowHeights=[12 * mm])
    amt.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e8eef7"))]))
    s += [amt, Spacer(0, 2 * mm),
          Paragraph(f"お支払期限：{due:%Y年%m月%d日}　　振込先：{R.ISSUER['bank']}", ST["n"]),
          Spacer(0, 5 * mm)]
    data = [["日付", "現場・内容", "人数", "単価", "金額"]]
    for d, site, n, rate, a in i["items"] + i["nontax"]:
        data.append([d, Paragraph(site, ST["n"]), n, f"{rate:,}" if rate != "" else "", f"{int(a):,}"])
    nlab = len(i["items"])
    if i["incl"]:
        foot = [["", "小計（人工代・税込）", "", "", f"{i['labor']:,}"],
                ["", "（内消費税10%）", "", "", f"({i['tax']:,})"]]
    else:
        foot = [["", "小計（人工代・税抜）", "", "", f"{i['labor']:,}"],
                ["", "消費税（10%）", "", "", f"{i['tax']:,}"]]
    if i["nontax"]:
        foot.append(["", "交通費・実費（不課税・立替）", "", "", f"{int(i['nontax_total']):,}"])
    foot.append(["", "合計（税込）", "", "", f"{int(i['total']):,}"])
    data += foot
    tb = Table(data, colWidths=[16 * mm, 92 * mm, 14 * mm, 22 * mm, 30 * mm], repeatRows=1)
    tb.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), F, 9.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde3ea")), ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEABOVE", (0, nlab + 1), (-1, nlab + 1), 1, colors.black),
        ("BACKGROUND", (0, -len(foot)), (-1, -1), colors.HexColor("#f4f6f8")),
        ("FONT", (0, -1), (-1, -1), F, 11),
    ]))
    s.append(tb)
    doc.build(s)


# ---------------- 給料 ----------------
def build_payroll(rows, notes):
    pay = OrderedDict()
    for r in sorted(rows, key=lambda x: (x["worker"], x["date"])):
        w = r["worker"]
        if w == "木ノ下":
            continue
        wage, incl = R.wage_rule(w, r["client"], r["night"], notes)
        p = pay.setdefault(w, dict(days=[], wage=0, km=0, ot=0, reimb=0))
        p["reimb"] += r["reimb"]
        trav = r["km"] * R.WAGE_KM
        if r["ot"]:
            notes.append(f"{w} {r['date']:%m/%d}: 残業{r['ot']}h → 給料側の残業単価ルールなし・未加算（要確認）")
        p["days"].append([f"{r['date'].month}/{r['date'].day}", r["client"], r["site"],
                          "夜" if r["night"] else "昼", wage, r["km"], trav])
        p["wage"] += wage
        p["km"] += r["km"]
    for w, p in pay.items():
        p["tax"] = math.floor(p["wage"] * R.TAX) if w in R.TAXED_WORKERS else 0
        p["trav"] = p["km"] * R.WAGE_KM
        p["total"] = p["wage"] + p["tax"] + p["trav"] + p["reimb"]
        p["gaichu"] = w in R.NAKAGAWA_GUMI
    return pay


def payroll_pdf(path, pay, ym, kinoshita_days):
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    s = [Paragraph(f"給料明細　{ym.year}年{ym.month}月分", ST["title"]), Spacer(0, 4 * mm),
         Paragraph(f"木ノ下 尚平：役員報酬 {yen(R.OFFICER_PAY)}（固定・加算なし／稼働 {kinoshita_days}日）", ST["n"]),
         PageBreak()]
    for idx, (w, p) in enumerate(pay.items()):
        kind = "（中川組・外注／請求書払い・税込）" if p["gaichu"] else ""
        s += [Paragraph(f"{w} 様　{ym.year}年{ym.month}月分 給料明細{kind}", ST["h"]), Spacer(0, 3 * mm)]
        data = [["日付", "取引先", "現場", "昼夜", "日当", "距離km", "交通費"]]
        for d in p["days"]:
            data.append([d[0], d[1], Paragraph(d[2], ST["s"]), d[3], f"{d[4]:,}", f"{d[5]:g}" if d[5] else "-", f"{int(d[6]):,}"])
        data += [["", f"稼働 {len(p['days'])}日", "", "", f"{p['wage']:,}", f"{p['km']:g}", f"{int(p['trav']):,}"]]
        tb = Table(data, colWidths=[15 * mm, 30 * mm, 55 * mm, 12 * mm, 22 * mm, 18 * mm, 22 * mm], repeatRows=1)
        tb.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde3ea")),
                                ("ALIGN", (4, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f4f6f8"))]))
        sm = [["日当合計", yen(p["wage"])]]
        if p["tax"]:
            sm.append(["消費税（10%）", yen(p["tax"])])
        sm.append([f"交通費（{p['km']:g}km × {R.WAGE_KM}円）", yen(p["trav"])])
        if p["reimb"]:
            sm.append(["立替精算（ETC等）", yen(p["reimb"])])
        sm.append(["支給合計", yen(p["total"])])
        st = Table(sm, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
        st.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 10), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), F, 12),
                                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e8eef7"))]))
        s += [tb, Spacer(0, 4 * mm), st,
              Paragraph("※ETCは木ノ下カード精算のため含みません（本人立替分は立替精算に計上）。", ST["s"])]
        if idx < len(pay) - 1:
            s.append(PageBreak())
    doc.build(s)


# ---------------- サマリー ----------------
def summary(rows, inv, pay, notes, ym, out):
    sales_ex = sum(i["sales_ex"] for i in inv.values())
    sales_in = sum(i["total"] for i in inv.values())
    wages = sum(p["wage"] + p["tax"] for p in pay.values())
    trav = sum(p["trav"] for p in pay.values())
    etc = sum(r["etc"] for r in rows)  # 本人立替分も含む（原価として1回だけ計上）
    reimb = sum(p["reimb"] for p in pay.values())
    other = sum(r["parking"] + r["fuel"] + r["lodging"] for r in rows)
    labor_total = wages + trav + R.OFFICER_PAY
    cost = labor_total + etc + other
    gp = sales_ex - cost
    rate = gp / sales_ex * 100 if sales_ex else 0
    uniq_notes = list(OrderedDict.fromkeys(notes))

    doc = SimpleDocTemplate(str(out / "月次サマリー.pdf"), pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=15 * mm, bottomMargin=15 * mm)
    ts = TableStyle([("FONT", (0, 0), (-1, -1), F, 9.5), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                     ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dde3ea")),
                     ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                     ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f4f6f8"))])
    s = [Paragraph(f"月次サマリー　{ym.year}年{ym.month}月", ST["title"]), Spacer(0, 5 * mm),
         Paragraph("1. 取引先別売上", ST["h"])]
    d = [["取引先", "人工数", "売上（税抜）", "消費税", "請求額（税込）"]]
    for c, i in inv.items():
        n = sum(v[0] for v in i["lines"].values())
        d.append([c, n, f"{int(i['sales_ex']):,}", f"{i['tax']:,}", f"{int(i['total']):,}"])
    d.append(["合計", sum(x[1] for x in d[1:]), f"{int(sales_ex):,}", f"{int(sales_in - sales_ex):,}", f"{int(sales_in):,}"])
    t = Table(d, colWidths=[50 * mm, 20 * mm, 35 * mm, 30 * mm, 35 * mm]); t.setStyle(ts)
    s += [t, Spacer(0, 5 * mm), Paragraph("2. 支払人件費一覧", ST["h"])]
    d = [["作業員", "稼働日", "日当(+税)", "交通費・立替", "支給合計"]]
    d.append(["木ノ下（役員報酬）", sum(1 for r in rows if r["worker"] == "木ノ下"), f"{R.OFFICER_PAY:,}", "0", f"{R.OFFICER_PAY:,}"])
    for w, p in pay.items():
        d.append([w + ("（外注）" if p["gaichu"] else ""), len(p["days"]), f"{p['wage'] + p['tax']:,}",
                  f"{int(p['trav'] + p['reimb']):,}", f"{int(p['total']):,}"])
    d.append(["支払合計", "", f"{wages + R.OFFICER_PAY:,}", f"{int(trav + reimb):,}", f"{int(labor_total + reimb):,}"])
    t = Table(d, colWidths=[50 * mm, 20 * mm, 35 * mm, 30 * mm, 35 * mm]); t.setStyle(ts)
    s += [t, Spacer(0, 5 * mm), Paragraph("3. 損益", ST["h"])]
    d = [["項目", "金額"], ["売上（税抜）", f"{int(sales_ex):,}"],
         ["人件費（役員報酬・作業員交通費込）", f"{int(labor_total):,}"],
         [f"ETC（うち本人立替 {int(reimb):,}）", f"{int(etc):,}"], ["駐車場・燃料・宿泊等", f"{int(other):,}"],
         ["原価合計", f"{int(cost):,}"], ["粗利", f"{int(gp):,}"], ["粗利率", f"{rate:.1f}%"]]
    t = Table(d, colWidths=[90 * mm, 50 * mm]); t.setStyle(ts)
    s += [t, Spacer(0, 5 * mm), Paragraph("4. 確認事項（仮計上）", ST["h"])]
    s += [Paragraph(f"・{n}", ST["n"]) for n in uniq_notes] or [Paragraph("なし", ST["n"])]
    doc.build(s)

    md = [f"# 月次サマリー {ym.year}年{ym.month}月", "", "| 取引先 | 売上(税抜) | 請求額(税込) |", "|---|---:|---:|"]
    md += [f"| {c} | {int(i['sales_ex']):,} | {int(i['total']):,} |" for c, i in inv.items()]
    md += [f"| **合計** | **{int(sales_ex):,}** | **{int(sales_in):,}** |", "",
           f"- 人件費合計（役員報酬込）: {int(labor_total):,}円", f"- ETC: {int(etc):,}円 / 駐車場・燃料・宿泊等: {int(other):,}円",
           f"- 粗利: {int(gp):,}円（粗利率 {rate:.1f}%）", "", "## 確認事項"] + [f"- {n}" for n in uniq_notes]
    (out / "月次サマリー.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return "\n".join(md)


def main(csv_path, ym_str=None):
    rows, notes = load(csv_path)
    if ym_str:
        ym = dt.date.fromisoformat(ym_str + "-01")
    else:
        ym = max(r["date"] for r in rows).replace(day=1)
    issue = ym.replace(day=calendar.monthrange(ym.year, ym.month)[1])
    nxt = (issue + dt.timedelta(days=1))
    due = nxt.replace(day=calendar.monthrange(nxt.year, nxt.month)[1])
    out = Path("out") / f"{ym:%Y-%m}"
    out.mkdir(parents=True, exist_ok=True)
    inv = build_invoices(rows, notes)
    for c in inv:
        if c not in R.CLIENT_LIST:
            notes.append(f"取引先「{c}」が協力業者一覧に未登録 → data/協力業者一覧.csv に追加すること")
        elif c not in R.ADDRESSES:
            notes.append(f"取引先「{c}」の住所が協力業者一覧に未登録")
    for n, (c, i) in enumerate(inv.items(), 1):
        invoice_pdf(out / f"請求書_{c}_{ym:%Y%m}.pdf", c, i, ym, f"TSG-{ym:%Y%m}-{n:02d}", issue, due)
    pay = build_payroll(rows, notes)
    payroll_pdf(out / f"給料明細_{ym:%Y%m}.pdf", pay, ym, sum(1 for r in rows if r["worker"] == "木ノ下"))
    print(summary(rows, inv, pay, notes, ym, out))
    # 月次まとめ: サマリー（売上・支払人件費・確認事項）→ 請求書 → 給料明細 を1冊に
    from pypdf import PdfWriter
    w = PdfWriter()
    for f in [out / "月次サマリー.pdf"] + sorted(out.glob("請求書_*.pdf")) + [out / f"給料明細_{ym:%Y%m}.pdf"]:
        w.append(str(f))
    w.write(str(out / f"月次まとめ_{ym:%Y%m}.pdf"))
    print(f"\n出力先: {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
