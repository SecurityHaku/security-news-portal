"""公開RSS/Atomフィードを収集して site/data/news.json を更新する。

- config/feeds.yaml のフィードを順に取得
- 2026-04-01 以降の記事のみ採用（要件）
- 既存 news.json とURL単位でマージ（既存のスコア等は保持）
- news.json が無い初回は news.seed.json を土台にする

使い方:
    python scripts/collect.py [--max-per-feed 40] [--since 2026-04-01]
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

# フィードが未来日付（予約投稿・日付表記の誤り）を返すことがある。
# 現在時刻より この猶予 を超えて先の記事は採用しない。
FUTURE_GRACE = timedelta(days=2)

import feedparser

import common as C


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        tm = entry.get(key)
        if tm:
            return datetime.fromtimestamp(time.mktime(tm), tz=timezone.utc)
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                return C.parse_iso(raw)
            except ValueError:
                pass
    return None


def collect(max_per_feed: int, since: datetime) -> None:
    feeds = C.load_feeds()

    existing = {item["id"]: item for item in C.load_news()}
    added, updated, skipped_old, skipped_future, errors = 0, 0, 0, 0, 0
    now = datetime.now(timezone.utc)
    future_cutoff = now + FUTURE_GRACE

    for feed in feeds:
        name, url = feed["name"], feed["url"]
        default_cat = feed.get("category", C.DEFAULT_CATEGORY)
        weight = float(feed.get("weight", 1.0))
        print(f"[collect] {name} ...", end=" ", flush=True)
        try:
            parsed = feedparser.parse(
                url, agent="security-news-portal/1.0 (+github actions)"
            )
        except Exception as exc:  # ネットワーク等
            print(f"ERROR ({exc})")
            errors += 1
            continue
        if parsed.bozo and not parsed.entries:
            print(f"WARN (取得失敗: {parsed.get('bozo_exception')})")
            errors += 1
            continue

        feed_added = 0
        for entry in parsed.entries[:max_per_feed]:
            dt = _entry_datetime(entry)
            if dt is None:
                continue
            if dt < since:
                skipped_old += 1
                continue
            if dt > future_cutoff:
                skipped_future += 1
                continue

            title = C.clean_text(entry.get("title"), limit=200)
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            summary = C.clean_text(
                entry.get("summary") or entry.get("description"), limit=320
            )
            item_id = C.make_id(link, title)
            category = C.categorize(title, summary, default_cat)
            cves = C.extract_cves(title, summary)

            record = {
                "id": item_id,
                "title": title,
                "url": link,
                "source": name,
                "source_weight": weight,
                "published": C.to_utc_iso(dt),
                "summary": summary,
                "category": category,
                "cves": cves,
                "seed": False,
            }

            if item_id in existing:
                prev = existing[item_id]
                # 原文が変わったら日本語化の結果は作り直させる（enrich.py が再生成）
                if prev.get("title") != title or prev.get("summary") != summary:
                    for k in ("title_ja", "summary_ja", "analysis_ja"):
                        prev.pop(k, None)
                # スコア関連の計算結果は score.py が再生成するので触らない
                prev.update(record)
                updated += 1
            else:
                existing[item_id] = record
                added += 1
                feed_added += 1
        print(f"OK (+{feed_added})")

    items = list(existing.values())
    # 実データが1件でも入ったら、初期サンプル(seed)は破棄する
    if any(not it.get("seed") for it in items):
        before = len(items)
        items = [it for it in items if not it.get("seed")]
        if before != len(items):
            print(f"[collect] サンプルデータ {before - len(items)} 件を除去")
    # 既存データに紛れ込んでいる未来日付の記事も掃除する
    cutoff_iso = C.to_utc_iso(future_cutoff)
    before = len(items)
    items = [it for it in items if it.get("published", "") <= cutoff_iso]
    if before != len(items):
        print(f"[collect] 未来日付の記事 {before - len(items)} 件を除去")
    C.save_news(items)
    print(
        f"\n[collect] 完了: 追加 {added} / 更新 {updated} / "
        f"期間外スキップ {skipped_old} / 未来日付スキップ {skipped_future} / エラー {errors}"
    )
    print(f"[collect] 総件数: {len(items)}  -> {C.NEWS_JSON}")
    if errors >= max(2, len(feeds) // 2) and added == 0 and updated == 0:
        print(
            "[collect] 注意: 多くのフィードでエラーかつ新規/更新なし。ネットワーク制限の"
            "可能性。GitHub Actions での実行を推奨。",
            file=sys.stderr,
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-feed", type=int, default=40)
    ap.add_argument("--since", default=C.MIN_DATE.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    since = C.parse_iso(args.since)
    since = max(since, C.MIN_DATE)  # 2026-04-01 より前は不可
    collect(args.max_per_feed, since)


if __name__ == "__main__":
    main()
