# 🛡️ Security News Portal

カテゴリ別の最新サイバーセキュリティニュースをダッシュボード表示し、
**月次レポート（PDF）の自動生成**と**月1回のメール配信**を行うプラットフォームです。

- **フロントエンド**: 素の HTML / CSS / JS（フレームワーク不使用）。GitHub Pages で公開
- **バッチ**: Python（収集 → 採点 → レポート → メール）
- **自動化**: GitHub Actions（週次でニュース更新、月次でレポート生成＋送信）
- **対象データ**: 公開 RSS/Atom フィード（JPCERT/CC・CISA 他）。2026年4月以降

---

## 目次
1. [できること](#できること)
2. [ディレクトリ構成](#ディレクトリ構成)
3. [処理フロー](#処理フロー)
4. [ローカルでのセットアップと実行](#ローカルでのセットアップと実行)
5. [メール送信の設定](#メール送信の設定)
6. [GitHub へのアップロード手順](#github-へのアップロード手順)
7. [GitHub Pages の公開](#github-pages-の公開)
8. [GitHub Actions（自動実行）の設定](#github-actions自動実行の設定)
9. [毎月の運用とカスタマイズ](#毎月の運用とカスタマイズ)
10. [トラブルシューティング](#トラブルシューティング)

---

## できること

| 機能 | 説明 |
|---|---|
| ダッシュボード | 8カテゴリ（脆弱性／ランサムウェア／APT／データ漏洩／クラウド・OSS／AI・LLM／規制／ツール・リサーチ）別にカード表示。KPI・注目トップ8（各カテゴリ1位）・検索・期間フィルタ・更新ボタン・ダーク/ライト切替。時刻はJST表示 |
| 日本語化 | 英語フィードの見出し・概要を日本語訳（`title_ja` / `summary_ja`）。無料の翻訳APIか Claude API を選択 |
| 着眼点／アナリスト見解 | 各月・各カテゴリで注目度1位の記事（最大8件）に、実務者向けの着眼点を付与（`analysis_ja`）。無料はルールベース、Claude API 使用時は一流アナリスト視点の見解 |
| 注目度スコア | 媒体の信頼度 × 新しさ × 複数媒体での言及数 × 高シグナル語 で自動算出しランキング |
| 月次レポート(PDF) | 対象月の各カテゴリ注目度1位（最大8件、概要＋着眼点＋カテゴリ＋リンク）＋月間サマリ。サイトと同じモダンなデザイン |
| メール配信 | 前月分レポートPDFを添付して自動送信（毎月1日）。手動送信も可 |
| 自動更新 | GitHub Actions が週次でニュース収集＋翻訳、月次でレポート生成・送信 |

> 日本語化・着眼点は **既定で完全無料**（MyMemory 翻訳API＋ルールベース生成、登録不要）。
> `ANTHROPIC_API_KEY` を設定すると Claude API による高品質版に自動で切り替わります（従量課金）。
> どちらも未設定でも英語のまま全機能が動作します。

> **注**: 初期状態では `site/data/news.seed.json` のサンプルデータを表示します。
> 初回の収集（`collect.py` または Actions）が走ると実データに置き換わります。

---

## ディレクトリ構成

```
06_security-news/
├── README.md                    このファイル
├── CLAUDE.md                    リポジトリ規約
├── requirements.txt            Python依存
├── .gitignore
├── .env.example                → .env にコピーして使う（SMTP設定）
├── メールアドレス.txt            送信先（.gitignoreで除外・非公開）
│
├── config/
│   └── feeds.yaml               収集対象フィード（ここだけで増減可能）
│
├── scripts/
│   ├── common.py                共通処理（パス/入出力/カテゴリ判定）
│   ├── collect.py               RSS収集 → site/data/news.json 更新
│   ├── score.py                 注目度スコア・月内順位を付与
│   ├── enrich.py                Claude APIで日本語訳＋アナリスト見解を付与
│   ├── generate_report.py       各カテゴリ注目1位（最大8件）でPDF生成（Playwright）
│   ├── send_email.py            レポートPDFをメール送信（自動/手動共通）
│   ├── serve.py                 ローカルプレビュー用HTTPサーバ
│   └── run_pipeline.ps1         収集→採点→日本語化→レポートを一括実行
│
├── templates/
│   └── report.html.j2           月次レポートのHTMLテンプレート
│
├── site/                        ← GitHub Pages で公開するディレクトリ
│   ├── index.html
│   ├── assets/css/style.css
│   ├── assets/js/app.js
│   ├── data/
│   │   ├── news.json            表示データ（ビルド成果物・コミット対象）
│   │   ├── meta.json            最終更新時刻・記事数（画面の「最終更新」表示用）
│   │   └── news.seed.json       初期サンプル
│   └── reports/
│       ├── index.json           生成済みレポート一覧（サイトが読む）
│       └── security-report-YYYY-MM.pdf   （生成物）
│
└── .github/workflows/
    ├── update-news.yml          週次: 収集＋採点
    └── monthly-report.yml       月次: 収集＋採点＋PDF＋メール
```

---

## 処理フロー

```
             ┌─────────────┐
 RSS/Atom ──▶│ collect.py  │  フィード取得・整形・カテゴリ判定・2026-04以降のみ採用
             └──────┬──────┘  → site/data/news.json
                    ▼
             ┌─────────────┐
             │  score.py   │  月ごとに 注目度スコア＋順位、各カテゴリ1位に featured
             └──────┬──────┘  → site/data/news.json / meta.json（更新）
                    ▼
             ┌─────────────┐
             │  enrich.py  │  全記事を日本語訳（title_ja/summary_ja）、
             │             │  featured（各月・各カテゴリ1位、最大8件）に着眼点/見解
             └──────┬──────┘  free=無料API+ルール / llm=Claude API（キー設定時）
                    ▼
             ┌──────────────────┐
             │ generate_report  │  featured（最大8件）＋サマリを report.html.j2 に描画
             │      .py         │  → Playwright(Chromium) で PDF化
             └──────┬───────────┘  → site/reports/security-report-YYYY-MM.pdf
                    ▼                 → site/reports/index.json（更新）
             ┌─────────────┐
             │send_email.py│  前月分PDFを添付し SMTP 送信
             └─────────────┘

  site/（静的） ─ GitHub Pages が配信。ブラウザが news.json / reports/ を読んで描画。
```

役割分担: **Actions がデータとPDFを更新してコミット** → **Pages がそれを表示**。
静的サイト単体ではRSS取得もメール送信もできないため、この分担にしています。

---

## ローカルでのセットアップと実行

### 前提
- Windows 11 / PowerShell
- Python 3.11 以上（`python --version` で確認）

### 1. 依存パッケージのインストール

```powershell
cd C:\Users\miwa3\.claude\projects\C--Users-miwa3\06_security-news

# 仮想環境（任意だが推奨）
python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt

# PDF変換用の Chromium を取得（初回のみ・数百MB）
python -m playwright install chromium
```

> `Activate.ps1` が「実行できない」と出る場合:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` を一度実行。

### 2. サイトをプレビュー

```powershell
python scripts/serve.py
# → ブラウザで http://127.0.0.1:8000
```

初期状態ではサンプルデータが表示されます。

### 3. 実データを収集してレポートまで作る

```powershell
# 収集 → 採点 → 前月のレポートPDF生成 を一括
.\scripts\run_pipeline.ps1

# 対象月を指定する場合
.\scripts\run_pipeline.ps1 -Month 2026-05
```

個別に実行する場合:

```powershell
python scripts/collect.py                       # RSS収集
python scripts/score.py                         # 採点
python scripts/generate_report.py --month 2026-05   # PDF生成
```

> **上海のネットワークからは一部フィード（Google/一部海外メディア）が取得できないことがあります。**
> その場合でもサンプル＋取得できたフィードで動作します。実データを確実に集めたい場合は
> GitHub Actions（後述）での実行を推奨します。

生成された PDF は `site/reports/security-report-YYYY-MM.pdf`。
サイトの「📄 月次レポート」ボタンからダウンロードできます。

---

## 日本語化・着眼点（enrich.py）

英語フィードの見出し・概要を日本語化し、**各月・各カテゴリで注目度1位の記事（最大8件＝
`score.py` が付ける `featured`）** に「着眼点」を付けます。この8件が、ダッシュボードの
「注目トップ8」・月次レポートの掲載記事と同じ集合です。
`enrich.py` には2つのエンジンがあり、`--engine auto`（既定）で自動選択します。

| エンジン | 翻訳 | 着眼点／見解 | コスト | 既定 |
|---|---|---|---|---|
| **free** | MyMemory 翻訳API（キー不要） | ルールベースの日本語アセスメント（カテゴリ・CVE・悪用有無・報道媒体数から生成） | **完全無料** | `ANTHROPIC_API_KEY` 未設定時 |
| **llm** | Claude API（高品質） | 一流アナリスト視点の見解を生成 | 従量課金（月あたり数十円〜） | `ANTHROPIC_API_KEY` 設定時 |

> **設定しなくても英語のまま全機能が動作します。** free エンジンも一切の登録・課金なしで使えます。

### 無料エンジン（既定）

追加設定は不要です。そのまま:

```powershell
python scripts/enrich.py                       # = --engine free（キー未設定時）
python scripts/enrich.py --engine free --month 2026-08
python scripts/enrich.py --engine free --force          # 作り直し
```

- **MyMemory の匿名枠は 1日およそ5000語**。超えるとその日の翻訳はそこで停止し、
  **次回実行（週次 Actions など）で自動的に続きを処理**します。着眼点の生成はオフラインなので常に完了します。
- 1日の上限を上げたい場合は `.env` に `MYMEMORY_EMAIL=you@example.com`（1日50000語）。
- 概要訳を付ける範囲は各月の注目上位 `ENRICH_FREE_SUMMARY_TOP_N` 位まで（既定20。タイトルは全件）。
- **着眼点は `featured`（各月・各カテゴリ1位、最大8件）に自動で付きます。** 範囲を変える設定はありません
  （増やしたい場合は `score.py` の featured 判定を編集）。ルールベースなのでオフライン・無課金・一瞬で完了します。

### LLM エンジンにアップグレード（任意・有料）

翻訳品質を上げ、着眼点を「一流アナリストの見解」に格上げしたい場合:

1. [Anthropic Console](https://console.anthropic.com/) で API キーを発行
2. `.env` に `ANTHROPIC_API_KEY=sk-ant-...`（`ENRICH_TRANSLATE_MODEL` / `ENRICH_ANALYSIS_MODEL` も任意で）
3. `python scripts/enrich.py`（キーがあれば自動で `llm`）。既存の free 結果は上書きされます。

コスト目安: 翻訳は Haiku で200記事 $0.1 未満、見解は Sonnet で **月あたり最大8件** なので $0.06 前後。
`ENRICH_*_MODEL` を `claude-opus-5` にすれば高品質・高コスト、`claude-haiku-4-5` 統一で最小コスト。

### 共通の挙動
- `run_pipeline.ps1` は `score` の後に自動で `enrich` を実行（`-SkipEnrich` で省略）。
- 付与済みの記事は再処理しません（`--force` で強制再生成）。
- `collect.py` は原文（タイトル/概要）が変わった記事の `*_ja` を破棄し、次の `enrich.py` で作り直させます。
- ダッシュボード／レポートは日本語があれば日本語で表示し、「原題」と
  「着眼点（自動生成）」または「アナリスト見解」（LLM時）を出します。

---

## メール送信の設定

### 送信先
`メールアドレス.txt` に1行1アドレスで記載（`#` 始まりと空行は無視）。
※このファイルは Git 管理外（非公開）です。

### SMTP（Gmail の例）
1. Google アカウントで2段階認証を有効化
2. [アプリパスワード](https://myaccount.google.com/apppasswords) を発行（16桁）
3. `.env.example` を `.env` にコピーして値を設定

```powershell
Copy-Item .env.example .env
notepad .env
```

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=あなたのアドレス@gmail.com
SMTP_PASS=発行した16桁のアプリパスワード
SMTP_FROM=あなたのアドレス@gmail.com
SMTP_STARTTLS=true
```

### 送信テスト・手動送信

```powershell
# 送信せず内容だけ確認
python scripts/send_email.py --month 2026-05 --dry-run

# 実際に送信（前月分なら --month 省略可）
python scripts/send_email.py --month 2026-05
```

> `.env` は `.gitignore` 済み。**絶対にコミットしないでください。**

---

## GitHub へのアップロード手順

このPCには **GitHub Desktop** が入っているため、その手順を主に説明します（コマンド版も後述）。

### A. GitHub 上でリポジトリを作る

1. https://github.com/new を開く
2. **Repository name**: 例 `security-news-portal`
3. 公開範囲: **Private** を推奨（Public でも可。ただし後述の注意を必ず確認）
4. 「Add a README」等は**チェックしない**（既にファイルがあるため）
5. **Create repository**

### B-1. GitHub Desktop でアップロード（推奨）

1. GitHub Desktop を起動 →  **File > Add local repository**
2. パスに `C:\Users\miwa3\.claude\projects\C--Users-miwa3\06_security-news` を指定
   - 「This directory does not appear to be a Git repository」と出たら
     **create a repository** をクリック
3. 「Create a Git repository」画面:
   - Name: `security-news-portal`
   - **Git ignore**: None（同梱の `.gitignore` を使うため）
   - **Create Repository** をクリック
4. 左下 **Summary** に `初回コミット` と入力 → **Commit to main**
5. 上部 **Publish repository** をクリック
   - Name を B-A で作った名前に合わせる（または新規作成させる）
   - **Keep this code private** に必要に応じてチェック
   - **Publish Repository**

これで GitHub にアップロードされます。以降はファイルを編集 → GitHub Desktop で
**Commit** → **Push origin** の繰り返しです。

### B-2. コマンドライン（Git Bash / PowerShell）でアップロード

`git` が PATH に無い場合、GitHub Desktop 同梱の git を使えます:

```powershell
# 同梱 git を今のセッションで使えるようにする
$env:Path += ";C:\Users\miwa3\AppData\Local\GitHubDesktop\app-3.6.4\resources\app\git\cmd"
git --version   # 動作確認（app-3.6.4 の数字は環境で変わることあり）
```

```powershell
cd C:\Users\miwa3\.claude\projects\C--Users-miwa3\06_security-news

git init
git branch -M main
git add .
git status                       # メールアドレス.txt / .env が含まれないことを確認
git commit -m "初回コミット: セキュリティニュースポータル一式"

# ↓ URL は A で作ったリポジトリのもの（HTTPS例）
git remote add origin https://github.com/<あなたのユーザー名>/security-news-portal.git
git push -u origin main
```

- 認証を求められたら、ブラウザ認証か
  [Personal Access Token](https://github.com/settings/tokens) を使用
  （パスワード欄にトークンを貼る）。

### アップロード前の必須チェック（重要）

```powershell
git status --ignored
```

- `メールアドレス.txt` と `.env` が **Untracked ではなく Ignored** に出ていることを確認
- 誤ってコミットしそうな場合は中断し、`.gitignore` を確認
- 万一コミット済みなら push 前に:
  `git rm --cached メールアドレス.txt .env`

> **Public にする場合の注意**: `site/data/news.json`（公開RSSの見出し・要約・リンク）と
> 生成PDFも公開されます。問題なければ Public で構いません。個人利用中心なら Private 推奨。

---

## GitHub Pages の公開

1. GitHub のリポジトリ → **Settings** → 左メニュー **Pages**
2. **Build and deployment** → Source: **Deploy from a branch**
3. Branch: **main** / フォルダ: **/(root)** ではなく… 本リポジトリは公開対象が
   `site/` サブフォルダのため、次のどちらかを選ぶ:
   - **方法1（簡単）**: Branch = `main`, Folder = `/docs` に変更したい場合は
     `site/` を `docs/` にリネーム（`git mv site docs`後、
     `scripts/common.py` の `SITE_DIR` を `"docs"` に変更）
   - **方法2（そのまま）**: Folder = `/ (root)` を選び、リポジトリ直下の
     `index.html` から `site/` へリダイレクトさせる（下記）
4. **Save** → 数分後 `https://<ユーザー名>.github.io/<リポジトリ名>/` で公開

### 方法2用: 直下リダイレクト（必要な場合のみ）

リポジトリ直下に `index.html` を作成:

```html
<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=./site/">
<a href="./site/">サイトへ移動</a>
```

> シンプルさ重視なら **方法1（`site/` → `docs/` リネーム）** が最もトラブルが少ないです。
> リネームした場合は `.github/workflows/*.yml` 内の `site/` も併せて置換してください。

---

## GitHub Actions（自動実行）の設定

### 1. Secrets を登録

リポジトリ → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
で以下を登録:

| 名前 | 値の例 | 用途 |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | SMTPサーバ |
| `SMTP_PORT` | `587` | ポート |
| `SMTP_USER` | `you@gmail.com` | SMTPユーザー |
| `SMTP_PASS` | `xxxxxxxxxxxxxxxx` | アプリパスワード |
| `SMTP_FROM` | `you@gmail.com` | 差出人 |
| `SMTP_STARTTLS` | `true` | STARTTLS使用 |
| `REPORT_RECIPIENTS` | `a@example.com, b@example.com` | 送信先（カンマ区切り可） |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | **任意**。設定すると日本語化・見解が Claude API の高品質版に切替（従量課金）。未設定なら無料エンジンで動作 |

> Actions では `メールアドレス.txt` が存在しない（非公開）ため、
> 送信先は必ず `REPORT_RECIPIENTS` に設定します。

無料エンジンの1日上限を上げたい場合や、LLMのモデルを変えたい場合は
**Settings → Secrets and variables → Actions → Variables**（Secretではなく変数）に
`MYMEMORY_EMAIL` / `ENRICH_FREE_SUMMARY_TOP_N` / `ENRICH_TRANSLATE_MODEL` /
`ENRICH_ANALYSIS_MODEL` を登録します（未設定なら既定値）。

### 2. ワークフローの権限

Settings → **Actions** → **General** → **Workflow permissions** を
**Read and write permissions** に設定（Actions が news.json / PDF をコミットするため）。

### 3. スケジュール

| ワークフロー | 既定スケジュール | 内容 |
|---|---|---|
| `update-news.yml` | 毎週月曜 06:00 JST | 収集＋採点＋コミット |
| `monthly-report.yml` | 毎月1日 09:00 JST | 収集＋採点＋PDF生成＋**メール送信** |

cron は UTC 表記です（`.yml` 内コメント参照）。変更する場合は各ファイルの
`schedule: - cron:` を編集。

### 4. 手動実行

リポジトリ → **Actions** タブ → 左でワークフローを選択 → **Run workflow**。
`monthly-report.yml` は対象月（空欄で前月）とメール送信ON/OFFを指定できます。

---

## 毎月の運用とカスタマイズ

### 毎月の確認ポイント
- Actions の `monthly-report` が成功しているか（Actions タブ）
- 受信箱にレポートメールが届いているか
- サイトの「月次レポート」に当月分が並んでいるか

### フィードを追加・変更する
`config/feeds.yaml` に追記するだけ:

```yaml
  - name: "表示名"
    url: "https://example.com/feed.xml"
    category: vulnerability      # 既定カテゴリ
    weight: 1.2                  # 信頼度の重み（1.0標準）
```

### カテゴリを変える
`scripts/common.py` の `CATEGORIES`（キー・ラベル・色）と
`site/assets/css/style.css` の `--c-*` 変数を**両方**編集。
自動分類のルールは同ファイルの `CATEGORY_RULES`。

### スコアの調整
`scripts/score.py` 冒頭の定数:
- `RECENCY_HALFLIFE_DAYS` … 新しさの効き（小さいほど直近重視）
- `JACCARD_THRESHOLD` … 同一話題とみなす類似度のしきい値
- `cluster_factor` の係数 … 複数媒体報道の加点幅

### レポートのデザイン
`templates/report.html.j2` の `<style>` を編集（サイトCSSと配色変数を合わせています）。
掲載件数は `generate_report.py --top N`。

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `collect.py` が全フィードERROR | ネットワーク制限。VPN経由か GitHub Actions で実行 |
| `playwright` で `Executable doesn't exist` | `python -m playwright install chromium` を実行 |
| Actions の PDF ステップで失敗 | ワークフローは `--with-deps` 付きでOS依存も導入済み。ログでフォント/権限エラーを確認 |
| メールが届かない | `--dry-run` で本文確認 → Secrets のスペル、Gmailはアプリパスワード必須、迷惑メールフォルダ |
| Actions がコミットできない | Workflow permissions を Read and write に |
| Pages が 404 | Settings > Pages のブランチ/フォルダ設定、`site/` か `docs/` かを再確認 |
| 日本語がPDFで豆腐(□) | Actions では Chromium 同梱フォントで表示可。ローカルで出る場合は Noto Sans JP / Yu Gothic を導入 |
| サンプルのまま変わらない | `collect.py` 実行後 `site/data/news.json` の中身と `git add` を確認 |

---

## ライセンス / 注意
- 収集するのは各フィードの見出し・要約・リンクのみ。全文転載はしません。再配布時は各媒体の規約を確認してください。
- 認証機構はありません。`serve.py` はローカル専用（127.0.0.1）。
- `.env` と `メールアドレス.txt` は公開リポジトリに含めないでください（`.gitignore` 済み）。
