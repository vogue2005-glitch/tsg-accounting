"""株式会社TSG 月次 請求・給料ルール（プロンプト記載ルールをそのまま定義）"""
import datetime as dt

ISSUER = {
    "name": "株式会社TSG",
    "rep": "代表取締役 木ノ下尚平",
    "zip": "〒424-0829",
    "addr": "静岡県静岡市清水区巴町10-20 島野ビル2F",
    "tel": "TEL 090-4850-4486",
    "reg": "登録番号 T9080001026912",
    "bank": "清水銀行 駒越支店 普通 3000931 カ）ティーエスジー",
}

TAX = 0.10
BILL_KM = 30      # 請求 交通費 円/km
WAGE_KM = 20      # 給料 交通費 円/km
OFFICER_PAY = 150_000  # 木ノ下 役員報酬

# 宛先: data/協力業者一覧.csv から読み込む（元請け情報が判明したら一覧に追記）
import csv as _csv
from pathlib import Path as _P
LIST_PATH = _P(__file__).resolve().parent.parent / "data" / "協力業者一覧.csv"
ADDRESSES = {}
CLIENT_LIST = set()
OFFICIAL = {}  # 請求書の宛名（正式名称）
with open(LIST_PATH, encoding="utf-8-sig") as _f:
    for _r in _csv.DictReader(_f):
        CLIENT_LIST.add(_r["取引先名"])
        if _r.get("正式名称"):
            OFFICIAL[_r["取引先名"]] = _r["正式名称"]
        if _r["住所"]:
            ADDRESSES[_r["取引先名"]] = (f"〒{_r['郵便番号']} " if _r["郵便番号"] else "") + _r["住所"]

# 取引先名の表記ゆれ → 正式キー
CLIENT_ALIAS = {
    "三共": "三共実業", "三共実業": "三共実業",
    "渡辺": "渡辺", "佐野": "佐野設備", "佐野設備": "佐野設備",
    "メンテック": "メンテック", "源馬": "源馬総合機設", "源馬機設": "源馬総合機設", "源馬総合機設": "源馬総合機設", "祭": "祭工業", "祭工業": "祭工業",
    "アスカ": "アスカ技建", "アスカ技建": "アスカ技建",
    "ユニットM": "ユニットM", "ユニットＭ": "ユニットM",
    "中川": "中川案件", "中川案件": "中川案件",
    "三田": "三田案件", "三田案件": "三田案件",
    "修善寺プリン工房": "修善寺プリン工房", "プリン工房": "修善寺プリン工房",
}

# 2026〜2027 国民の祝日（振替含む）
HOLIDAYS = {dt.date(*d) for d in [
    (2026, 1, 1), (2026, 1, 12), (2026, 2, 11), (2026, 2, 23), (2026, 3, 20),
    (2026, 4, 29), (2026, 5, 3), (2026, 5, 4), (2026, 5, 5), (2026, 5, 6),
    (2026, 7, 20), (2026, 8, 11), (2026, 9, 21), (2026, 9, 22), (2026, 9, 23),
    (2026, 10, 12), (2026, 11, 3), (2026, 11, 23), (2027, 1, 1), (2027, 1, 11),
    (2027, 2, 11), (2027, 2, 23), (2027, 3, 21), (2027, 3, 22),
]}


def is_holiday(d: dt.date) -> bool:
    return d.weekday() >= 5 or d in HOLIDAYS


def bill_rule(client, site, night, holiday, notes):
    """請求単価を返す: (単価, 税込か, 残業時給, 交通費請求方式, 労務費率)
    交通費方式: 'km'=30円/km+ETC実費, 'receipt'=領収書実費, 'none'=請求しない"""
    if client == "メンテック":
        return 23_000, False, 23_000 / 8 * 1.25, "km", 0
    if client == "ユニットM":
        return 12_000, False, 0, "none", 0
    if client == "アスカ技建":
        return 25_000, False, 30_000 / 8 * 1.25, "km", 0
    if client == "中川案件":  # 単価は案件ごとに異なる → CSVの「請求単価」列で毎回指定
        notes.append(f"中川案件（{site}）: 請求単価が未確認 → 0円で計上中。単価を確認して入力すること")
        return 0, False, 30_000 / 8 * 1.25, "km", 0
    if client == "三田案件":
        return 12_000, True, 0, "receipt", 0
    if client == "修善寺プリン工房":
        notes.append("修善寺プリン工房の請求単価が未定義 → 仮に12,000円税込で計上")
        return 12_000, True, 0, "receipt", 0
    ot = 30_000 / 8 * 1.25
    if client == "祭工業" and night:
        if "横浜" in site:
            return 25_000, False, ot, "km", 0
        notes.append(f"祭工業 夜勤（横浜以外: {site}）→ 通常夜勤30,000円で仮計上")
    if client == "源馬総合機設":  # 20,000＋税、夜勤1.5倍
        if holiday and not night:
            notes.append("源馬総合機設 休日昼の単価未確認 → 基本ルール30,000円で仮計上")
            return 30_000, False, 30_000 / 8 * 1.25, "km", 0
        return (30_000 if night else 20_000), False, 30_000 / 8 * 1.25, "km", 0
    rate = 30_000 if (night or holiday) else 20_000
    lab = 0.10 if client == "佐野設備" else 0
    if client not in ("三共実業", "渡辺", "佐野設備", "祭工業"):
        notes.append(f"取引先「{client}」は個別ルールなし → 基本単価で仮計上")
    return rate, False, ot, "km", lab


# ---- 給料 ----
WORKER_ALIAS = {"金丸": "たかし", "たかし（金丸）": "たかし", "コニー": "コニ"}
NAKAGAWA_GUMI = {"中川", "望月"}  # 中川組（外注・税込）
TAXED_WORKERS = {"原", "縣"}       # 給料＋消費税10%

# 取引先区分別 日当（昼, 夜）。None=ルール記載なし
WAGE_TABLE = {
    "たかし": {"sankyo": (14_000, 21_000), "sano": (15_000, None), "mentec": (16_000, None), "matsuri": (14_000, 22_000)},
    "黒澤":   {"sankyo": (16_000, None), "sano": (17_000, None), "mentec": (18_000, None), "matsuri": (None, 24_000)},
    "中川組": {"sankyo": (17_000, None), "sano": (17_000, None), "mentec": (17_000, None), "matsuri": (17_000, 22_000)},
    "富岡":   {"sankyo": (16_000, 24_000), "sano": (17_000, 24_000), "mentec": (17_000, 24_000), "*": (None, 24_000)},
}
# 作業員×取引先の個別単価（昼, 夜）。表より優先
WORKER_CLIENT_WAGE = {
    ("黒澤", "源馬総合機設"): (16_000, None),
}
FLAT_WAGE = {  # 取引先によらない（昼, 夜）
    "近藤": (15_000, 22_500), "原": (18_000, 27_000),
    "諸星": (15_000, 22_500), "堀口": (15_000, 22_500), "コニ": (15_000, 22_500),
    "平石": (13_000, 19_500), "すまいりー": (13_000, 19_500), "主水": (13_000, 19_500),
    "縣": (18_000, None), "古澤": (18_000, None), "後藤組": (13_000, None), "大ちゃん": (15_000, None),
}


def client_cat(client):
    return {"三共実業": "sankyo", "渡辺": "sankyo", "佐野設備": "sano",
            "メンテック": "mentec", "祭工業": "matsuri"}.get(client, "*")


def wage_rule(worker, client, night, notes):
    """作業員日当を返す: (日当, 税込/外注フラグ)"""
    if worker == "木ノ下":
        return 0, False
    if client in ("修善寺プリン工房", "三田案件"):
        return 12_000, True
    if client == "アスカ技建":
        return (20_000 if worker == "黒澤" else 19_000), False
    if (worker, client) in WORKER_CLIENT_WAGE:
        day, nt = WORKER_CLIENT_WAGE[(worker, client)]
        if night and nt is None:
            nt = round(day * 1.5)
            notes.append(f"{worker}: {client} 夜勤単価未定義 → 昼×1.5={nt:,}円で仮計上")
        return (nt if night else day), False
    key = "中川組" if worker in NAKAGAWA_GUMI else worker
    if key in WAGE_TABLE:
        t = WAGE_TABLE[key]
        cat = client_cat(client)
        day, nt = t.get(cat) or t.get("*") or t.get("sankyo")
        if cat not in t:
            notes.append(f"{worker}: 取引先「{client}」の単価未定義 → 三共・渡辺単価で仮計上")
            day, nt = t.get("sankyo", (day, nt))
        if night:
            if nt is None:
                nt = round((day or 0) * 1.5)
                notes.append(f"{worker}: {client} 夜勤単価未定義 → 昼×1.5={nt:,}円で仮計上")
            return nt, key == "中川組"
        if day is None:
            notes.append(f"{worker}: {client} 昼単価未定義 → 0円（要確認）")
            return 0, False
        return day, key == "中川組"
    if worker in FLAT_WAGE:
        day, nt = FLAT_WAGE[worker]
        if night:
            if nt is None:
                nt = round(day * 1.5)
                notes.append(f"{worker}: 夜勤単価未定義 → 昼×1.5={nt:,}円で仮計上")
            return nt, False
        return day, False
    notes.append(f"作業員「{worker}」の単価未定義 → 0円（要確認）")
    return 0, False
