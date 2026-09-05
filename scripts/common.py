"""共通ユーティリティ: パス解決 / news.json 入出力 / テキスト整形 / カテゴリ判定。

依存を持たない（標準ライブラリのみ）。collect / score / generate_report / send_email
から import して使う。
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# --- パス ---------------------------------------------------------------------
# scripts/ の親がリポジトリルート（= 06_security-news）
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SITE_DIR = REPO_ROOT / "site"
DATA_DIR = SITE_DIR / "data"
REPORTS_DIR = SITE_DIR / "reports"
TEMPLATES_DIR = REPO_ROOT / "templates"

NEWS_JSON = DATA_DIR / "news.json"
NEWS_SEED_JSON = DATA_DIR / "news.seed.json"
META_JSON = DATA_DIR / "meta.json"   # パイプライン最終実行時刻（画面の「最終更新」表示用）
FEEDS_YAML = CONFIG_DIR / "feeds.yaml"
RECIPIENTS_FILE = REPO_ROOT / "メールアドレス.txt"

# 2026年4月以降のニュースのみ扱う（要件）
MIN_DATE = datetime(2026, 4, 1, tzinfo=timezone.utc)

# --- カテゴリ定義 ------------------------------------------------------------
# label: 画面/レポートの表示名, color: アクセント色（サイトCSSと合わせる）
CATEGORIES: dict[str, dict[str, str]] = {
    "vulnerability":  {"label": "脆弱性",              "color": "#f97316"},
    "ransomware":     {"label": "ランサムウェア",        "color": "#ef4444"},
    "apt":            {"label": "APT・脅威アクター",     "color": "#a855f7"},
    "data-breach":    {"label": "データ漏洩",            "color": "#ec4899"},
    "cloud-oss":      {"label": "クラウド・OSS",         "color": "#38bdf8"},
    "ai":             {"label": "AI・LLMセキュリティ",   "color": "#14b8a6"},
    "regulation":     {"label": "規制・コンプライアンス", "color": "#22c55e"},
    "tools-research": {"label": "ツール・リサーチ",       "color": "#eab308"},
}
DEFAULT_CATEGORY = "tools-research"

# キーワードによる再分類ルール（上から順に評価し、最初に一致したものを採用）。
# 「ランサム/漏洩/APT が併記されたら脆弱性より優先」させたいので順序が重要。
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("ransomware", [
        "ransomware", "ランサム", "lockbit", "alphv", "blackcat", "clop", "cl0p",
        "black basta", "double extortion", "data leak site", "身代金",
    ]),
    ("data-breach", [
        "data breach", "breach", "leaked", "data leak", "exposed database",
        "情報漏えい", "情報漏洩", "個人情報", "exfiltrat", "stolen data",
        "unsecured", "misconfigured bucket", "records exposed",
    ]),
    ("apt", [
        "apt", "nation-state", "nation state", "state-sponsored", "state sponsored",
        "lazarus", "volt typhoon", "salt typhoon", "sandworm", "fancy bear",
        "espionage", "threat actor", "advanced persistent", "標的型",
    ]),
    ("ai", [
        "genai", "gen ai", "generative ai", "ai-powered", "ai powered",
        "ai-generated", "ai model", "ai models", "ai agent", "ai agents",
        "agentic ai", "ai assistant", "ai chatbot", "ai system", "ai security",
        "llm", "large language model", "prompt injection", "jailbreak",
        "model poisoning", "training data", "chatgpt", "openai", "anthropic",
        "claude ", "gemini", "copilot", "deepfake", "hugging face",
        "model context protocol", "mcp server", "生成ai", "機械学習モデル",
    ]),
    ("regulation", [
        "gdpr", "nis2", "nis 2", "dora", "hipaa", "regulation", "compliance",
        "regulator", "regulatory", "fined", "penalty", "規制", "法規制",
        "ガイドライン", "executive order", "sanction", "sec disclosure",
    ]),
    ("cloud-oss", [
        "aws", "azure", "google cloud", "gcp", "kubernetes", "container",
        "open source", "open-source", "npm", "pypi", "supply chain",
        "github action", "docker", "saas", "iam", "s3 bucket", "oauth",
    ]),
    ("vulnerability", [
        "cve-", "vulnerability", "zero-day", "zero day", "0-day", "rce",
        "remote code execution", "privilege escalation", "patch tuesday",
        "security update", "actively exploited", "脆弱性", "パッチ", "flaw",
        "buffer overflow", "sql injection", "authentication bypass",
    ]),
    ("tools-research", [
        "research", "researchers", "released", "open-sourced", "poc",
        "proof of concept", "new tool", "framework", "analysis", "study",
    ]),
]

# 注目度スコアを底上げする高シグナル語（レポートの「注目理由」にも使う）
HIGH_SIGNAL_KEYWORDS = [
    "critical", "actively exploited", "exploited in the wild", "zero-day",
    "zero day", "0-day", "emergency", "urgent", "mass exploitation",
    "unauthenticated", "緊急", "悪用",
]

CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_STOPWORDS = {
    "the", "a", "an", "to", "of", "in", "on", "for", "and", "with", "from",
    "new", "say", "says", "said", "after", "over", "into", "amid", "as", "at",
    "by", "is", "are", "be", "how", "why", "what", "this", "that", "its",
    # 定型の連載・掲載枠タイトル（これで束ねると過剰クラスタになる）
    "weekly", "report", "roundup", "briefing", "bulletin", "update", "updates",
    "week", "daily", "digest", "podcast", "episode", "recap", "news",
}


# --- テキスト整形 ----------------------------------------------------------
def clean_text(raw: str | None, limit: int = 320) -> str:
    """HTMLタグ・エンティティを除去し、空白を正規化して指定長で切る。"""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def extract_cves(*texts: str) -> list[str]:
    """複数テキストからCVE IDを抽出（大文字化・重複排除・出現順維持）。"""
    seen: list[str] = []
    for t in texts:
        for m in CVE_RE.findall(t or ""):
            cid = m.upper()
            if cid not in seen:
                seen.append(cid)
    return seen


def categorize(title: str, summary: str, feed_default: str) -> str:
    """タイトル+要約からカテゴリを判定。ルール未一致ならフィード既定値。"""
    blob = f"{title} {summary}".lower()
    for category, keywords in CATEGORY_RULES:
        if any(kw in blob for kw in keywords):
            return category
    return feed_default if feed_default in CATEGORIES else DEFAULT_CATEGORY


def title_tokens(title: str) -> set[str]:
    """類似記事のクラスタリング用: タイトルを正規化してトークン集合に。"""
    words = re.sub(r"[^a-z0-9\s]", " ", title.lower()).split()
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def make_id(url: str, title: str) -> str:
    key = (url or title).strip().lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# --- 日付 ------------------------------------------------------------------
def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def month_key(value) -> str:
    """datetime or ISO文字列 -> 'YYYY-MM'"""
    dt = value if isinstance(value, datetime) else parse_iso(value)
    return dt.strftime("%Y-%m")


def previous_month_key(ref: datetime | None = None) -> str:
    ref = ref or datetime.now(timezone.utc)
    year, month = ref.year, ref.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


# --- feeds.yaml 読み込み（PyYAML非依存の簡易パーサ）--------------------
def _coerce(value: str):
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def load_feeds(path: Path | None = None) -> list[dict]:
    """config/feeds.yaml を読む。

    想定する構造だけを解釈する簡易パーサ:
        feeds:
          - name: "..."
            url: "..."
            category: vulnerability
            weight: 1.2
    行頭 '#' と空行は無視。フルYAMLは扱わない（この用途に十分なため）。
    """
    path = path or FEEDS_YAML
    feeds: list[dict] = []
    current: dict | None = None
    in_feeds = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.strip() == "feeds:":
            in_feeds = True
            continue
        if not in_feeds:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current:
                feeds.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None:
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            current[key.strip()] = _coerce(val)
    if current:
        feeds.append(current)
    return [f for f in feeds if f.get("url")]


# --- news.json 入出力 ----------------------------------------------------
def load_news(fallback_to_seed: bool = True) -> list[dict]:
    if NEWS_JSON.exists():
        return json.loads(NEWS_JSON.read_text(encoding="utf-8"))
    if fallback_to_seed and NEWS_SEED_JSON.exists():
        return json.loads(NEWS_SEED_JSON.read_text(encoding="utf-8"))
    return []


def save_news(items: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda x: x.get("published", ""), reverse=True)
    NEWS_JSON.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_meta(len(items))


def write_meta(article_count: int) -> None:
    """画面の「最終更新」用メタ情報。パイプライン実行のたびに現在時刻で更新する。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    META_JSON.write_text(
        json.dumps(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "articles": article_count,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
