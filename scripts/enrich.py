"""ニュースの日本語化と「着眼点／アナリスト見解」の付与。

エンジン（--engine）:
    free  無料。MyMemory 翻訳API（キー不要・無課金）＋ ルールベースの日本語アセスメント。
    llm   Claude API。高品質な翻訳＋一流アナリスト視点の見解。ANTHROPIC_API_KEY 必須（課金あり）。
    auto  ANTHROPIC_API_KEY があれば llm、無ければ free（既定）。
    off   何もしない。

付与フィールド: title_ja / summary_ja / analysis_ja / enriched_by ("free" | "llm")

着眼点／見解は「各月・各カテゴリで注目度1位の記事（score.py が付ける featured=True、
最大7件）」だけに付ける。これは画面の「注目トップ7」・月次レポートの掲載記事と同じ集合。

free エンジンの注意:
    MyMemory の匿名枠は 1日あたり約5000語。超えるとその日の翻訳はそこで停止し、
    次回実行で続きを処理する（着眼点の生成はオフラインなので常に実行される）。
    環境変数 MYMEMORY_EMAIL を設定すると 1日50000語まで拡大できる。

使い方:
    python scripts/enrich.py                     # auto。未処理をすべて
    python scripts/enrich.py --engine free
    python scripts/enrich.py --month 2026-08 --force
    python scripts/enrich.py --limit 50          # 翻訳API呼び出しの上限（試運転）
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import common as C

# --- 設定 ----------------------------------------------------------------
TRANSLATE_MODEL = os.environ.get("ENRICH_TRANSLATE_MODEL", "claude-haiku-4-5")
ANALYSIS_MODEL = os.environ.get("ENRICH_ANALYSIS_MODEL", "claude-sonnet-5")
# 概要の翻訳を付ける範囲（各月の rank 上位）。着眼点は featured 記事のみで別管理。
FREE_SUMMARY_TOP_N = int(os.environ.get("ENRICH_FREE_SUMMARY_TOP_N") or 20)
TRANSLATE_BATCH = 12

MYMEMORY_URL = "https://api.mymemory.translated.net/get"
MYMEMORY_EMAIL = os.environ.get("MYMEMORY_EMAIL", "").strip()


# ======================================================================
#  無料エンジン（MyMemory 翻訳 + ルールベース・アセスメント）
# ======================================================================
_mm_blocked = False
_mm_cache: dict[str, str] = {}
_mm_fails = 0          # 連続失敗カウント（一定数でその回は打ち切り）
MM_PACING_SEC = 1.2   # リクエスト間隔（MyMemory のレート制限対策）


def _split_for_api(text: str, limit: int = 460) -> list[str]:
    """MyMemory の q は約500文字まで。文単位で分割する。"""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts, buf = [], ""
    for sent in re.split(r"(?<=[.!?。！？])\s+", text):
        if len(buf) + len(sent) + 1 > limit and buf:
            parts.append(buf.strip())
            buf = ""
        buf += sent + " "
        while len(buf) > limit:  # 1文が長すぎる場合の強制分割
            parts.append(buf[:limit])
            buf = buf[limit:]
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _mm_request(chunk: str) -> str | None:
    """1チャンクを翻訳。429は指数バックオフで再試行。恒久失敗は None。"""
    global _mm_blocked
    params = {"q": chunk, "langpair": "en|ja"}
    if MYMEMORY_EMAIL:
        params["de"] = MYMEMORY_EMAIL
    url = MYMEMORY_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            time.sleep(MM_PACING_SEC)
            with urllib.request.urlopen(url, timeout=25) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                wait = int(exc.headers.get("Retry-After") or 0) or (2 ** (attempt + 1))
                print(f"[enrich] 429 レート制限。{wait}s 待機して再試行", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[enrich] 翻訳API HTTP {exc.code}", file=sys.stderr)
            return None
        except Exception as exc:
            print(f"[enrich] 翻訳API通信失敗: {exc}", file=sys.stderr)
            return None
        rd = data.get("responseData") or {}
        translated = html.unescape(rd.get("translatedText") or "")
        upper = translated.upper()
        if data.get("responseStatus") != 200 or "QUOTA" in upper or "MYMEMORY WARNING" in upper:
            print(f"[enrich] MyMemory 日次上限に到達（次回続行）: {translated[:100]}", file=sys.stderr)
            _mm_blocked = True
            return None
        return translated or None
    return None


def translate_free(text: str, budget: list[int]) -> str:
    """MyMemory で英->日。制限到達 or 連続失敗で "" を返し以降スキップ。"""
    global _mm_fails
    text = (text or "").strip()
    if not text or _mm_blocked or budget[0] == 0:
        return ""
    if text in _mm_cache:
        return _mm_cache[text]

    out = []
    for chunk in _split_for_api(text):
        res = _mm_request(chunk)
        if res is None:
            _mm_fails += 1
            if _mm_fails >= 6:
                print("[enrich] 翻訳の連続失敗が続くため今回は打ち切り（次回続行）", file=sys.stderr)
                globals()["_mm_blocked"] = True
            return ""
        _mm_fails = 0
        out.append(res)
        if budget[0] > 0:
            budget[0] -= 1

    result = " ".join(out).strip()
    _mm_cache[text] = result
    return result


# カテゴリ別の「想定される影響」「推奨される対応」テンプレート
_IMPACT = {
    "vulnerability": "該当製品・バージョンを利用している場合、リモートからの侵害や権限奪取につながる可能性がある。",
    "ransomware": "業務システムの停止やデータ暗号化・窃取による二次被害（恐喝・公開）のリスクがある。",
    "apt": "高度な攻撃者による長期潜伏・情報窃取を想定する必要があり、検知の難易度が高い。",
    "data-breach": "漏えいした資格情報や個人情報が、なりすまし・標的型攻撃の起点として悪用される恐れがある。",
    "cloud-oss": "クラウド設定や依存パッケージ経由で、複数システムに横断的な影響が及ぶ可能性がある。",
    "ai": "生成AI・LLMの利用箇所（社内チャットボット、コード補完、AIエージェント等）で、プロンプトインジェクションや情報漏えい・不正操作につながる可能性がある。",
    "regulation": "対応期限や報告義務が生じる場合があり、社内プロセス・契約条項の見直しが必要になりうる。",
    "tools-research": "攻撃・防御いずれの手法にも転用されうるため、脅威動向として把握しておく価値がある。",
}
_ACTION = {
    "vulnerability": "資産管理台帳で該当有無を確認し、提供されていればパッチ適用、無ければ回避策と監視を強化する。",
    "ransomware": "オフライン/イミュータブルなバックアップの検証、EDRの検知強化、初期侵入経路（VPN・RDP・フィッシング）の点検を行う。",
    "apt": "該当IOC・TTPでのスレットハンティング、ログ保全期間の延長、多要素認証と特権アクセスの棚卸しを実施する。",
    "data-breach": "影響ユーザーへの通知方針を確認し、パスワード強制リセットと不審ログインの監視を行う。",
    "cloud-oss": "IAM権限と公開範囲の再点検、依存パッケージのバージョン固定と署名検証、SBOMの整備を進める。",
    "ai": "AI利用のガイドライン整備、入出力のフィルタリング・最小権限化、AIエージェントの操作範囲の制限、社外AIサービスへの機微情報入力の管理を行う。",
    "regulation": "適用対象か法務と確認し、必要なら報告フロー・データ処理記録・委託先管理を更新する。",
    "tools-research": "自組織の検知ルール・演習シナリオへの反映余地を評価する。",
}


def rule_assessment(it: dict) -> str:
    """LLMを使わない、シグナルベースの日本語アセスメント（3〜5文）。"""
    cat_label = C.CATEGORIES.get(it.get("category"), {}).get("label", "セキュリティ")
    blob = f"{it.get('title','')} {it.get('summary','')}".lower()
    s: list[str] = []

    s.append(f"本件は「{cat_label}」分野のニュースで、{it.get('source','')}が報じた。")

    sev: list[str] = []
    if any(k in blob for k in ("actively exploited", "exploited in the wild",
                               "in the wild", "under active", "zero-day", "zero day", "0-day")):
        sev.append("実環境での悪用が報告されており緊急度が高い")
    elif "critical" in blob or "緊急" in blob:
        sev.append("深刻度が高いと位置づけられている")
    if it.get("cves"):
        sev.append(f"CVE（{', '.join(it['cves'][:3])}）が採番されている")
    if any(k in blob for k in ("patch", "update available", "fixed in", "hotfix", "security update")):
        sev.append("修正版またはパッチが提供されている")
    elif any(k in blob for k in ("poc", "proof of concept", "exploit code", "exploit is available")):
        sev.append("PoC（実証コード）が公開されている")
    if sev:
        s.append("、".join(sev) + "。")

    s.append(_IMPACT.get(it.get("category"), _IMPACT["tools-research"]))
    s.append("推奨対応: " + _ACTION.get(it.get("category"), _ACTION["tools-research"]))

    size = it.get("cluster_size", 1)
    if size >= 3:
        s.append(f"複数（{size}媒体）が取り上げており、業界的な注目度は高い。")
    elif size == 2:
        s.append("2つの媒体が取り上げている。")
    elif it.get("source_weight", 1.0) >= 1.3:
        s.append("一次情報に近い主要ソースからの報道である。")
    return "".join(s)


def run_free(items: list[dict], scope: list[dict], force: bool, budget: list[int],
             only_translate: bool = False, only_analysis: bool = False) -> None:
    ranked = sorted(
        (it for it in scope if it.get("rank")),
        key=lambda x: (C.month_key(x["published"]), x["rank"]),
    )

    if not only_analysis:
        # 1) タイトル訳（全件・短文）
        n = 0
        for it in scope:
            if _mm_blocked:
                break
            if force or not it.get("title_ja"):
                ja = translate_free(it["title"], budget)
                if ja:
                    it["title_ja"] = C.clean_text(ja, limit=200)
                    it["enriched_by"] = "free"
                    n += 1
        print(f"[enrich/free] タイトル訳: {n} 件")

        # 2) 概要訳（各月 上位 FREE_SUMMARY_TOP_N 位まで）
        n = 0
        for it in ranked:
            if _mm_blocked:
                break
            if it["rank"] > FREE_SUMMARY_TOP_N:
                continue
            if force or not it.get("summary_ja"):
                ja = translate_free(it.get("summary", ""), budget)
                if ja:
                    it["summary_ja"] = C.clean_text(ja, limit=400)
                    it["enriched_by"] = "free"
                    n += 1
        print(f"[enrich/free] 概要訳: {n} 件" + ("（翻訳上限に到達）" if _mm_blocked else ""))

    if not only_translate:
        # 3) 着眼点（各月・各カテゴリ1位=featured のみ。オフラインなので常に実行）
        n = 0
        for it in ranked:
            if not it.get("featured"):
                continue
            if force or not it.get("analysis_ja"):
                it["analysis_ja"] = rule_assessment(it)
                it.setdefault("enriched_by", "free")
                n += 1
        print(f"[enrich/free] 着眼点（自動生成）: {n} 件")


# ======================================================================
#  LLM エンジン（Claude API）
# ======================================================================
TRANSLATE_SYSTEM = (
    "あなたはサイバーセキュリティ専門の翻訳者です。英語のセキュリティニュースの"
    "見出しと概要を、正確で自然な日本語に翻訳します。CVE番号・製品名・組織名・"
    "攻撃グループ名は一般的な日本語表記を使い、必要なら英語を併記します。"
    "誇張や創作をせず、原文にある事実だけを訳します。"
)
ANALYSIS_SYSTEM = (
    "あなたは大手セキュリティベンダーの一流脅威インテリジェンス・アナリストです。"
    "個々のニュースについて、日本の企業・組織の実務者向けに、簡潔で示唆に富んだ"
    "「アナリスト見解」を日本語で書きます。次の観点を自然な文章で織り込みます: "
    "(1) 何が起きたか／何が新しいか (2) 想定される影響と対象範囲 "
    "(3) 推奨される対応・着眼点 (4) この件が注目される理由。"
    "3〜5文。原文にない固有名詞・CVE番号・数値を創作しない。"
    "断定できない点は「可能性がある」と明示する。前置きや箇条書きは使わず、"
    "見解の本文のみを返す。"
)


def _fatal(exc: Exception) -> bool:
    return type(exc).__name__ in {"AuthenticationError", "PermissionDeniedError", "NotFoundError"}


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _extract_json_array(s: str):
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("JSON配列が見つからない")
    return json.loads(s[start:end + 1])


def get_llm_client():
    try:
        import anthropic
    except ImportError:
        print("[enrich] anthropic 未インストール。`pip install anthropic`", file=sys.stderr)
        return None
    try:
        return anthropic.Anthropic()
    except Exception as exc:
        print(f"[enrich] Anthropic 初期化失敗: {exc}", file=sys.stderr)
        return None


def _llm_translate_batch(client, batch: list[dict]) -> dict[str, dict]:
    payload = [{"id": it["id"], "title": it["title"], "summary": it.get("summary", "")}
               for it in batch]
    user = (
        "次の記事を日本語に翻訳してください。各記事について "
        '{"id": 元のid, "title_ja": 見出しの訳, "summary_ja": 概要の訳（2〜3文に整える）} '
        "を作り、JSON配列だけを返してください（前後の説明文なし）。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    resp = client.messages.create(
        model=TRANSLATE_MODEL, max_tokens=4000, system=TRANSLATE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    rows = _extract_json_array(_text(resp))
    return {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}


def _llm_analyze_one(client, it: dict) -> str:
    facts = {
        "title": it["title"], "summary": it.get("summary", ""),
        "source": it.get("source", ""),
        "category": C.CATEGORIES.get(it.get("category"), {}).get("label", ""),
        "cves": it.get("cves", []), "published": it.get("published", "")[:10],
    }
    resp = client.messages.create(
        model=ANALYSIS_MODEL, max_tokens=1200, system=ANALYSIS_SYSTEM,
        messages=[{"role": "user",
                   "content": "次のニュースについて、日本の実務者向けの『アナリスト見解』を書いてください。\n\n"
                              + json.dumps(facts, ensure_ascii=False)}],
    )
    return _text(resp)


def run_llm(items: list[dict], scope: list[dict], force: bool, budget: list[int],
            only_translate: bool, only_analysis: bool) -> None:
    client = get_llm_client()
    if client is None:
        return

    if not only_analysis:
        todo = [it for it in scope if force or not it.get("title_ja")]
        for i in range(0, len(todo), TRANSLATE_BATCH):
            if budget[0] == 0:
                break
            chunk = todo[i:i + TRANSLATE_BATCH]
            try:
                mapped = _llm_translate_batch(client, chunk)
            except Exception as exc:
                if _fatal(exc):
                    raise SystemExit(f"[enrich] 中断: {exc}")
                print(f"[enrich/llm] 翻訳バッチ失敗（スキップ）: {exc}", file=sys.stderr)
                continue
            for it in chunk:
                r = mapped.get(it["id"])
                if not r:
                    continue
                it["title_ja"] = C.clean_text(r.get("title_ja"), limit=200) or it.get("title_ja")
                it["summary_ja"] = C.clean_text(r.get("summary_ja"), limit=400) or it.get("summary_ja")
                it["enriched_by"] = "llm"
                if budget[0] > 0:
                    budget[0] -= 1
            print(f"[enrich/llm] 翻訳 {min(i + len(chunk), len(todo))}/{len(todo)}")

    if not only_translate:
        targets = [it for it in scope
                   if it.get("featured")
                   and (force or not it.get("analysis_ja") or it.get("enriched_by") != "llm")]
        targets.sort(key=lambda x: (C.month_key(x["published"]), x.get("rank", 999)))
        done = 0
        for it in targets:
            if budget[0] == 0:
                break
            try:
                txt = _llm_analyze_one(client, it)
            except Exception as exc:
                if _fatal(exc):
                    raise SystemExit(f"[enrich] 中断: {exc}")
                print(f"[enrich/llm] 見解生成失敗（スキップ）: {exc}", file=sys.stderr)
                continue
            if txt:
                it["analysis_ja"] = txt
                it["enriched_by"] = "llm"
                done += 1
                if budget[0] > 0:
                    budget[0] -= 1
            print(f"[enrich/llm] 見解 {done}/{len(targets)}  {it['title'][:48]}")


# ======================================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["auto", "free", "llm", "off"], default="auto")
    ap.add_argument("--month", default=None, help="対象を YYYY-MM に限定")
    ap.add_argument("--only-translate", action="store_true")
    ap.add_argument("--only-analysis", action="store_true")
    ap.add_argument("--force", action="store_true", help="付与済みも再生成")
    ap.add_argument("--limit", type=int, default=-1, help="翻訳API呼び出しの上限（-1=無制限）")
    args = ap.parse_args()

    engine = args.engine
    if engine == "auto":
        engine = "llm" if os.environ.get("ANTHROPIC_API_KEY") else "free"
    if engine == "off":
        print("[enrich] engine=off。何もしません。")
        return

    items = C.load_news()
    if not items:
        print("[enrich] news.json が空。先に collect.py を実行してください。")
        return
    scope = items
    if args.month:
        scope = [it for it in items if C.month_key(it["published"]) == args.month]
    print(f"[enrich] engine={engine} / 対象 {len(scope)} 件"
          + (f" / 月 {args.month}" if args.month else ""))

    budget = [args.limit]
    if engine == "free":
        run_free(items, scope, args.force, budget,
                 args.only_translate, args.only_analysis)
    else:  # llm
        run_llm(items, scope, args.force, budget, args.only_translate, args.only_analysis)

    C.save_news(items)
    print(f"[enrich] 保存: {C.NEWS_JSON}")


if __name__ == "__main__":
    main()
