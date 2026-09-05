"""月次レポート（PDF）を生成する。

- 対象月の掲載記事＝各カテゴリの注目度1位（score.py の featured、最大8件）＋月間サマリを
  HTML テンプレートに流し込み、Playwright(Chromium) で PDF 化する。
- 出力: site/reports/security-report-YYYY-MM.pdf
- site/reports/index.json（利用可能なレポート一覧）も更新する。サイトの
  「月次レポート」ボタンがこれを読む。

使い方:
    python scripts/generate_report.py                 # 前月
    python scripts/generate_report.py --month 2026-05
    python scripts/generate_report.py --month 2026-05 --top 5
環境変数 REPORT_MONTH でも対象月を指定可（--month 優先）。
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

from jinja2 import Environment, FileSystemLoader, select_autoescape

import common as C


def _why(item: dict) -> str:
    """レポートに載せる「注目理由」を組み立てる。"""
    reasons: list[str] = []
    size = item.get("cluster_size", 1)
    if size >= 2:
        reasons.append(f"{size}媒体が報道")
    blob = f"{item['title']} {item.get('summary', '')}".lower()
    if any(k in blob for k in ("actively exploited", "exploited in the wild", "悪用")):
        reasons.append("悪用が確認")
    if any(k in blob for k in ("critical", "緊急", "emergency")):
        reasons.append("深刻度が高い")
    if item.get("cves"):
        reasons.append("CVE採番あり")
    if item.get("source_weight", 1.0) >= 1.3 and "主要媒体が報道" not in reasons:
        reasons.append("主要媒体が報道")
    return "・".join(dict.fromkeys(reasons)) or "編集部ピックアップ"


def build_context(month: str, top: int) -> dict:
    items = [it for it in C.load_news() if C.month_key(it["published"]) == month]
    if not items:
        raise SystemExit(
            f"[report] {month} のニュースが0件です。collect.py / score.py を先に実行してください。"
        )
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    # 掲載記事＝各カテゴリで注目度1位（score.py の featured）。最大7件。
    featured = [it for it in items if it.get("featured")]
    top_items = (featured or items)[:top]
    for it in top_items:
        it["why"] = _why(it)
        # 日本語版があれば優先（無ければ原文フォールバック）
        it["title_disp"] = it.get("title_ja") or it["title"]
        it["summary_disp"] = it.get("summary_ja") or it.get("summary", "")
        it["analysis"] = it.get("analysis_ja", "")
        it["analysis_label"] = (
            "アナリスト見解" if it.get("enriched_by") == "llm" else "着眼点（自動生成）"
        )
        it["category_label"] = C.CATEGORIES[it["category"]]["label"]
        it["category_color"] = C.CATEGORIES[it["category"]]["color"]
        it["published_date"] = C.parse_iso(it["published"]).strftime("%Y-%m-%d")

    cat_counter = Counter(it["category"] for it in items)
    categories = [
        {
            "key": key,
            "label": C.CATEGORIES[key]["label"],
            "color": C.CATEGORIES[key]["color"],
            "count": cat_counter.get(key, 0),
        }
        for key in C.CATEGORIES
    ]
    max_count = max((c["count"] for c in categories), default=1) or 1
    for c in categories:
        c["bar_pct"] = round(100 * c["count"] / max_count)

    src_counter = Counter(it["source"] for it in items)
    y, m = month.split("-")

    return {
        "month": month,
        "month_label": f"{y}年{int(m)}月",
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "total": len(items),
        "categories": [c for c in categories if c["count"] > 0],
        "top_sources": src_counter.most_common(5),
        "top_items": top_items,
        "top_n": len(top_items),
    }


def render_html(ctx: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(C.TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template("report.html.j2").render(**ctx)


def html_to_pdf(html_path, pdf_path) -> bool:
    """Playwright(Chromium) で HTML を PDF 化。使えない環境では False を返す。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[report] playwright 未インストールのため PDF 生成をスキップします。")
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
            browser.close()
        return True
    except Exception as exc:
        print(f"[report] PDF 生成に失敗（HTML は生成済み）: {exc}")
        print("[report] ヒント: python -m playwright install chromium")
        return False


def update_index(month: str, ctx: dict, pdf_name: str | None, html_name: str) -> None:
    index_path = C.REPORTS_DIR / "index.json"
    entries = []
    if index_path.exists():
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    entries = [e for e in entries if e["month"] != month]
    entries.append(
        {
            "month": month,
            "month_label": ctx["month_label"],
            "file": pdf_name or html_name,  # サイトはこれを開く（PDF優先）
            "pdf": pdf_name,
            "html": html_name,
            "total": ctx["total"],
            "top_n": ctx["top_n"],
            "generated_at": ctx["generated_at"],
        }
    )
    entries.sort(key=lambda e: e["month"], reverse=True)
    index_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM（未指定なら前月）")
    ap.add_argument("--top", type=int, default=8,
                    help="掲載上限（既定8＝カテゴリ数）")
    args = ap.parse_args()

    month = args.month or os.environ.get("REPORT_MONTH") or ""
    month = month.strip() or C.previous_month_key()
    datetime.strptime(month, "%Y-%m")  # 形式チェック

    C.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ctx = build_context(month, args.top)
    html = render_html(ctx)

    html_name = f"security-report-{month}.html"
    pdf_name = f"security-report-{month}.pdf"
    html_path = C.REPORTS_DIR / html_name
    pdf_path = C.REPORTS_DIR / pdf_name

    html_path.write_text(html, encoding="utf-8")  # HTML版は常に生成（それ自体が成果物）
    made_pdf = html_to_pdf(html_path, pdf_path)

    update_index(month, ctx, pdf_name if made_pdf else None, html_name)

    print(f"[report] HTML: {html_path}")
    if made_pdf:
        print(f"[report] PDF : {pdf_path}  ({pdf_path.stat().st_size/1024:.0f} KB)")
    else:
        print(f"[report] PDF は未生成。{html_name} をブラウザで開き Ctrl+P → PDF保存でも可。")
    print(f"[report] 対象月 {ctx['month_label']} / 全{ctx['total']}件 / 上位{ctx['top_n']}件を掲載")


if __name__ == "__main__":
    main()
