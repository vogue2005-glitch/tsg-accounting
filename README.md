# TSG 月次 請求書・人件費

終了報告をCSV（`data/sample.csv` と同じ列）にして実行:

    python3 -m tsg.generate data/2026-11.csv

`out/YYYY-MM/` に出力されるもの: 取引先別の請求書PDF、給料明細PDF、月次サマリー（PDF/MD、確認事項付き）。
単価・宛先は `tsg/rules.py` で管理しています。

## 運用
- 月の途中の終了報告は `data/YYYY-MM.csv` に追記していく（この時点では作成しない）
- 「最終」報告（月の最後の仕事日）を受けたら一括作成 → `月次まとめ_YYYYMM.pdf`
  （月次サマリー・支払人件費一覧・確認事項 → 各社請求書 → 給料明細 の1冊）
