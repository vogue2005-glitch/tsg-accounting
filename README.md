# TSG 月次 請求書・人件費

終了報告をCSV（`data/sample.csv` と同じ列）にして実行:

    python3 -m tsg.generate data/2026-11.csv

`out/YYYY-MM/` に出力されるもの: 取引先別の請求書PDF、給料明細PDF、月次サマリー（PDF/MD、確認事項付き）。
単価・宛先は `tsg/rules.py` で管理しています。
