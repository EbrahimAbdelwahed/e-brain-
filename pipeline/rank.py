from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

import yaml

from .io import db, fetch_articles_by_ids, fetch_cluster_members, fetch_clusters


def _load_weights(path: str = "config/sources.yml") -> dict[str, float]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {s["id"]: float(s.get("weight", 1)) for s in data.get("sources", [])}


def _freshness_decay(published_at_list: list[str | None]) -> float:
    # Use 1 / (1 + days_since_max)
    dates = []
    for p in published_at_list:
        if not p:
            continue
        try:
            dates.append(datetime.strptime(p, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))
        except Exception:  # noqa: BLE001
            continue
    if not dates:
        return 0.0
    latest = max(dates)
    days = (datetime.now(timezone.utc) - latest).total_seconds() / 86400.0
    return 1.0 / (1.0 + max(0.0, days))


def score_clusters() -> list[dict[str, Any]]:
    weights = _load_weights()
    with db() as conn:
        clusters = fetch_clusters(conn)
    scored: list[dict[str, Any]] = []
    for c in clusters:
        with db() as conn:
            members = fetch_cluster_members(conn, c["cluster_id"])  # list of article_ids
            arts = fetch_articles_by_ids(conn, members)
        source_weights = [weights.get(a.get("source_id"), 1.0) for a in arts]
        sw = sum(source_weights) / len(source_weights) if source_weights else 1.0
        fr = _freshness_decay([a.get("published_at") for a in arts])
        cs = min(1.0, len(arts) / 5.0)
        score = 0.5 * fr + 0.3 * sw + 0.2 * cs
        scored.append({"cluster_id": c["cluster_id"], "score": score, "size": len(arts)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored

