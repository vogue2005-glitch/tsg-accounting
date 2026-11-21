"""予定 × 終了報告 の突合チェック（監査担当用）

使い方: python3 -m tsg.check data/2026-11_予定.csv data/2026-11.csv [基準日 YYYY-MM-DD]
  基準日（省略時=今日）までの予定のうち、終了報告が無いもの／予定に無い報告／
  単価未登録の作業員・取引先を一覧表示する。ファイルは変更しない。
"""
import csv
import datetime as dt
import re
import sys

from . import rules as R
from .generate import load, parse_date

SKIP = {"未定", "未記載", ""}


def known_worker(w):
    return (w == "木ノ下" or w in R.NAKAGAWA_GUMI or w in R.WAGE_TABLE
            or w in R.FLAT_WAGE or any(k[0] == w for k in R.WORKER_CLIENT_WAGE))


def load_plan(path):
    plan = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not (r.get("日付") or "").strip():
                continue
            d = parse_date(r["日付"])
            client = R.CLIENT_ALIAS.get(r["取引先"].strip(), r["取引先"].strip())
            raw = (r.get("作業員") or "").strip()
            pending = []
            for w in re.split(r"[・、,]", raw):
                w = re.sub(r"[（(].*?[)）]", "", w).strip()
                w = R.WORKER_ALIAS.get(w, w)
                if w == "中川組" or w in SKIP:
                    pending.append(raw or "（空欄）")
                    continue
                plan.append((d, client, w, (r.get("現場") or "").strip()))
            if pending:
                plan.append((d, client, None, f"作業員未確定: {raw or '（空欄）'}"))
    return plan


def main(plan_path, actual_path, asof=None):
    asof = dt.date.fromisoformat(asof) if asof else dt.date.today()
    plan = load_plan(plan_path)
    rows, _ = load(actual_path)
    done = {(r["date"], r["client"], r["worker"]) for r in rows}
    planned = {(d, c, w) for d, c, w, _ in plan if w}
    issues = []

    for d, c, w, site in sorted(plan, key=lambda x: (x[0], x[1], x[2] or "")):
        if d > asof:
            continue
        if w is None:
            issues.append(f"[作業員未確定] {d:%m/%d} {c}: {site}")
        elif (d, c, w) not in done:
            issues.append(f"[報告なし]     {d:%m/%d} {c} {w}（{site or '現場未記載'}）")
    for d, c, w in sorted(done - planned):
        issues.append(f"[予定外の報告] {d:%m/%d} {c} {w}（予定表に無い／取引先・日付ずれ？）")

    workers = {r["worker"] for r in rows} | {w for _, _, w, _ in plan if w}
    for w in sorted(workers):
        if not known_worker(w):
            issues.append(f"[単価未登録]   作業員「{w}」が tsg/rules.py に無い")
    clients = {r["client"] for r in rows} | {c for _, c, _, _ in plan}
    for c in sorted(clients):
        if c not in R.CLIENT_LIST:
            issues.append(f"[取引先未登録] 「{c}」が data/協力業者一覧.csv に無い")
        elif c not in R.ADDRESSES:
            issues.append(f"[住所未登録]   「{c}」")
    for r in rows:
        if "後日" in r["memo"] or "要確認" in r["memo"]:
            issues.append(f"[保留]         {r['date']:%m/%d} {r['client']} {r['worker']}: {r['memo']}")

    print(f"突合チェック（{asof}時点）: {len(issues)}件")
    for i in issues:
        print("  " + i)
    return issues


if __name__ == "__main__":
    main(*sys.argv[1:4])
