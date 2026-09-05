"""各ニュースの「注目度スコア」を計算して news.json に書き戻す。

スコアの考え方（月ごとに独立して評価）:
    score = source_weight          # 媒体の信頼度（feeds.yaml の weight）
          * recency_factor         # 新しいほど高い（半減期14日の指数減衰）
          * cluster_factor         # 複数媒体が同じ話題を報じるほど高い
          * keyword_boost          # "critical" 等の高シグナル語で加点

同じ話題のクラスタリングは「タイトル語のJaccard類似度 >= 0.5」または
「共通のCVE IDを持つ」で判定する。クラスタ内で source_weight 最大の記事を
代表としてスコアを満額、それ以外は 0.6 掛けにする（重複表示の抑制）。

使い方:
    python scripts/score.py
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import common as C

RECENCY_HALFLIFE_DAYS = 14.0
JACCARD_THRESHOLD = 0.5
NON_REPRESENTATIVE_FACTOR = 0.6


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cluster(items: list[dict]) -> list[list[int]]:
    """items内のインデックスを類似グループに分割（union-find的な素朴実装）。"""
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    tokens = [C.title_tokens(it["title"]) for it in items]
    cves = [set(it.get("cves") or []) for it in items]
    for i in range(n):
        for j in range(i + 1, n):
            same_cve = bool(cves[i] & cves[j])
            if same_cve or _jaccard(tokens[i], tokens[j]) >= JACCARD_THRESHOLD:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _recency_factor(published_iso: str, now: datetime) -> float:
    age_days = max((now - C.parse_iso(published_iso)).total_seconds() / 86400.0, 0.0)
    return math.pow(0.5, age_days / RECENCY_HALFLIFE_DAYS)


def _keyword_boost(item: dict) -> float:
    blob = f"{item['title']} {item.get('summary', '')}".lower()
    hits = sum(1 for kw in C.HIGH_SIGNAL_KEYWORDS if kw in blob)
    return 1.0 + 0.15 * hits


def score_all() -> None:
    items = C.load_news()
    if not items:
        print("[score] news.json が空。先に collect.py を実行してください。")
        return

    now = datetime.now(timezone.utc)
    by_month: dict[str, list[dict]] = {}
    for it in items:
        by_month.setdefault(C.month_key(it["published"]), []).append(it)

    for month, month_items in by_month.items():
        clusters = _cluster(month_items)
        for group in clusters:
            group_items = [month_items[i] for i in group]
            cluster_size = len(group_items)
            cluster_factor = 1.0 + 0.5 * (cluster_size - 1)
            rep_idx = max(
                range(cluster_size),
                key=lambda k: group_items[k].get("source_weight", 1.0),
            )
            for k, it in enumerate(group_items):
                base = (
                    it.get("source_weight", 1.0)
                    * _recency_factor(it["published"], now)
                    * cluster_factor
                    * _keyword_boost(it)
                )
                if k != rep_idx:
                    base *= NON_REPRESENTATIVE_FACTOR
                it["score"] = round(base, 4)
                it["cluster_size"] = cluster_size

        # 月内の順位を付与
        for rank, it in enumerate(
            sorted(month_items, key=lambda x: x["score"], reverse=True), start=1
        ):
            it["rank"] = rank

        # 各カテゴリで最もスコアの高い記事に featured=True を立てる。
        # 画面の「注目トップ7」・月次レポートの掲載記事・着眼点の対象は、この集合。
        best_by_cat: dict[str, dict] = {}
        for it in month_items:
            it["featured"] = False
            cur = best_by_cat.get(it["category"])
            if cur is None or it["score"] > cur["score"]:
                best_by_cat[it["category"]] = it
        for it in best_by_cat.values():
            it["featured"] = True

    C.save_news(items)
    print(f"[score] 完了: {len(items)} 件, {len(by_month)} か月分を採点 -> {C.NEWS_JSON}")


if __name__ == "__main__":
    score_all()
