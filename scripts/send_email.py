"""月次レポートPDFをメール送信する（自動実行・手動実行 共通）。

宛先の決定順:
    1. 環境変数 REPORT_RECIPIENTS（カンマ/改行/空白区切り）  ← Actions ではこれ
    2. 06_security-news/メールアドレス.txt の各行            ← ローカルではこれ
       （空行と # で始まる行は無視）

SMTP設定は環境変数（.env / Actions Secrets）:
    SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS SMTP_FROM SMTP_STARTTLS

使い方:
    python scripts/send_email.py                  # 前月分を送信
    python scripts/send_email.py --month 2026-05
    python scripts/send_email.py --dry-run        # 送信せず内容だけ表示
"""
from __future__ import annotations

import argparse
import os
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import common as C

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_dotenv(path: Path) -> None:
    """依存を増やさないための最小 .env ローダ。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def resolve_recipients() -> list[str]:
    raw = os.environ.get("REPORT_RECIPIENTS", "").strip()
    if raw:
        candidates = re.split(r"[,\s]+", raw)
    elif C.RECIPIENTS_FILE.exists():
        candidates = [
            ln.strip()
            for ln in C.RECIPIENTS_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    else:
        candidates = []

    valid = [c for c in candidates if EMAIL_RE.match(c)]
    invalid = [c for c in candidates if c and not EMAIL_RE.match(c)]
    for c in invalid:
        print(f"[email] 宛先の形式が不正: {c!r}（スキップ）", file=sys.stderr)
    return valid


def build_message(month: str, report_path: Path, sender: str, recipients: list[str]) -> EmailMessage:
    items = [it for it in C.load_news() if C.month_key(it["published"]) == month]
    items.sort(key=lambda x: x.get("score", 0), reverse=True)
    top5 = items[:5]
    y, m = month.split("-")
    month_label = f"{y}年{int(m)}月"

    lines = [
        f"{month_label} の月次セキュリティニュースレポートをお届けします。",
        f"（収集記事 {len(items)} 件 / 注目ピックアップ {len(top5)} 件）",
        "",
        "■ 今月の注目ニュース",
    ]
    for i, it in enumerate(top5, 1):
        cat = C.CATEGORIES[it["category"]]["label"]
        date = C.parse_iso(it["published"]).strftime("%m/%d")
        lines.append(f"{i}. [{cat}] {it['title']} ({it['source']}, {date})")
        lines.append(f"   {it['url']}")
    lines += [
        "",
        "詳細は添付のPDFレポートをご覧ください。",
        "",
        "-- ",
        "このメールはセキュリティニュースポータルから自動送信されています。",
    ]

    msg = EmailMessage()
    msg["Subject"] = f"【月次】セキュリティニュースレポート {month_label}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))

    data = report_path.read_bytes()
    if report_path.suffix == ".pdf":
        msg.add_attachment(data, maintype="application", subtype="pdf",
                           filename=report_path.name)
    else:
        msg.add_attachment(data, maintype="text", subtype="html",
                           filename=report_path.name)
    return msg


def send(msg: EmailMessage) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    use_starttls = os.environ.get("SMTP_STARTTLS", "true").lower() != "false"

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            if user:
                s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as s:
            s.ehlo()
            if use_starttls:
                s.starttls(context=ctx)
                s.ehlo()
            if user:
                s.login(user, password)
            s.send_message(msg)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="YYYY-MM（未指定なら前月）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(C.REPO_ROOT / ".env")

    month = (args.month or os.environ.get("REPORT_MONTH") or "").strip() or C.previous_month_key()
    datetime.strptime(month, "%Y-%m")

    pdf_path = C.REPORTS_DIR / f"security-report-{month}.pdf"
    html_path = C.REPORTS_DIR / f"security-report-{month}.html"
    report_path = pdf_path if pdf_path.exists() else html_path
    if not report_path.exists():
        raise SystemExit(
            f"[email] レポートが見つかりません: {pdf_path}\n"
            f"       先に  python scripts/generate_report.py --month {month}  を実行してください。"
        )

    recipients = resolve_recipients()
    if not recipients:
        raise SystemExit(
            "[email] 有効な宛先がありません。メールアドレス.txt を作成するか "
            "環境変数 REPORT_RECIPIENTS を設定してください。"
        )

    sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or ""
    msg = build_message(month, report_path, sender, recipients)

    if args.dry_run:
        print("=== DRY RUN（送信しません） ===")
        print(f"From   : {sender}")
        print(f"To     : {', '.join(recipients)}")
        print(f"Subject: {msg['Subject']}")
        print(f"Attach : {report_path.name} ({report_path.stat().st_size/1024:.0f} KB)")
        print("--- 本文 ---")
        body = msg.get_body(preferencelist=("plain",))
        print(body.get_content() if body else "(本文なし)")
        return

    if not os.environ.get("SMTP_HOST"):
        raise SystemExit("[email] SMTP_HOST 等が未設定です（.env / Secrets を確認）。")

    send(msg)
    print(f"[email] 送信完了: {len(recipients)} 宛先 / {report_path.name}")


if __name__ == "__main__":
    main()
