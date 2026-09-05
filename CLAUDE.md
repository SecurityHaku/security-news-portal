# CLAUDE.md

## 概要
カテゴリ別のサイバーセキュリティニュースを集約・可視化するダッシュボードと、
月次レポート(PDF)の自動生成・メール配信を行うプラットフォーム。
2026年4月以降のニュースを対象とする。機能全体は README.md を参照。

## 構成
- `site/` … 静的フロントエンド（GitHub Pages で公開）。`data/news.json` を読んで描画する
- `scripts/` … Pythonバッチ（収集→採点→レポート→メール）
- `templates/report.html.j2` … 月次レポートのHTMLテンプレート（Playwrightで PDF化）
- `config/feeds.yaml` … 収集対象フィードの定義。フィード追加はここだけで完結
- `.github/workflows/` … 自動実行（update-news = 週次収集 / monthly-report = 月次PDF+メール）

## データフロー
collect.py（RSS取得・正規化・カテゴリ判定・未来日付は除外） → score.py（注目度スコア・
月内順位・各カテゴリ1位に featured=True） → enrich.py（日本語訳 title_ja/summary_ja、
featured に analysis_ja、enriched_by を記録） → generate_report.py（featured=最大8件で
PDF生成、site/reports/ に出力＋index.json更新） → send_email.py（前月分PDFを添付してSMTP送信）

- **カテゴリは8種**（common.CATEGORIES）: vulnerability / ransomware / apt / data-breach /
  cloud-oss / ai / regulation / tools-research。色は style.css の `--c-*` と app.js の
  CATEGORIES と3か所一致させる。
- **featured**: score.py が月ごとに「各カテゴリでスコア最大の1件」に立てるフラグ。最大8件。
  画面の「注目トップ8」・月次レポート掲載記事・着眼点の対象は、すべてこの集合。
- **meta.json**: common.save_news() が毎回 `updated_at`（UTC ISO）と `articles` を書く。
  画面の「最終更新」はこれを **JST** に整形して表示（無ければ最新記事日で代替）。
  レポートの生成日時も JST（generate_report.py の `JST` 定数）。
- **更新ボタン**（app.js #refreshBtn）: news.json / meta.json を再取得して再描画するだけ。
  実クロールはしない（静的サイトのため。収集は collect.py / Actions）。
- **未来日付の除外**: collect.py が `published > now + FUTURE_GRACE(2日)` の記事を捨てる
  （フィードの予約投稿・日付誤りで 11月付け等が混ざるため）。

enrich.py は2エンジン（--engine auto が既定）:
- free（既定・無料）: MyMemory翻訳API（キー不要、1日約5000語、超過で _mm_blocked→次回続行、
  429は指数バックオフ）＋ rule_assessment()（オフラインのルールベース着眼点、常に完走）。
- llm（ANTHROPIC_API_KEY があれば自動選択）: Claude API。翻訳=ENRICH_TRANSLATE_MODEL、
  見解=ENRICH_ANALYSIS_MODEL。着眼点対象は featured のみ（最大8件/月）。
原文が変わると collect.py が該当の *_ja を破棄し、次の enrich で作り直す。
新しい依存を足す前に必ず確認（argostranslate は torch を引き込むため不採用）。

`site/data/news.json` はビルド成果物だが、Pagesが読むためリポジトリにコミットする。
`site/data/news.seed.json` は初期表示用サンプル（`seed: true`）。初回 collect で実データに置換。

## 規約・注意
- インデントは Python 4 / JS・CSS・YAML 2 スペース
- コメントは「なぜ」を書く
- カテゴリの定義（キー・ラベル・色）は `scripts/common.py` の `CATEGORIES` と
  `site/assets/css/style.css` の `--c-*` 変数を**両方**一致させる
- 認証情報・宛先メール（`.env` / `メールアドレス.txt`）はコミットしない（.gitignore済）
- フィード取得は feedparser 既定（HTTPS・証明書検証あり）。検証を無効化しない
- `serve.py` は 127.0.0.1 のみバインド（認証なしのため 0.0.0.0 にしない）

## よく使うコマンド（PowerShell）
- 一括: `.\scripts\run_pipeline.ps1 -Month 2026-05`（.env を自動読込。`-SkipEnrich` で日本語化省略）
- 収集: `python scripts/collect.py`
- 採点: `python scripts/score.py`
- 日本語化: `python scripts/enrich.py [--engine free|llm] [--month 2026-05] [--only-analysis] [--force] [--limit N]`
- レポート: `python scripts/generate_report.py --month 2026-05`（featured 最大8件を掲載）
- 送信テスト: `python scripts/send_email.py --month 2026-05 --dry-run`
- プレビュー: `python scripts/serve.py` → http://127.0.0.1:8000
