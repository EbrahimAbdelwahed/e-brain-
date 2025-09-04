from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import yaml

from .io import db, fetch_articles_by_ids, fetch_cluster_members, fetch_clusters


def _load_weights(path: str = "config/sources.yml") -> dict[str, float]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {s["id"]: float(s.get("weight", 1)) for s in data.get("sources", [])}


def _freshness_decay(published_at_list: list[str | None]) -> float:
    """Exponential freshness decay with configurable half-life (hours).

    freshness = exp(-ln(2) * age_hours / half_life_hours)
    """
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
    age_hours = (datetime.now(timezone.utc) - latest).total_seconds() / 3600.0
    if age_hours < 0:
        age_hours = 0.0
    try:
        half_life_hours = int(os.getenv("RANK_HALF_LIFE_HOURS", "24"))
        if half_life_hours <= 0:
            half_life_hours = 24
    except Exception:  # noqa: BLE001
        half_life_hours = 24
    # exp(-ln(2) * t / T_half) == 2 ** (-t / T_half)
    freshness = 2 ** (-(age_hours / float(half_life_hours)))
    # Guard numerical issues
    if freshness < 0:
        freshness = 0.0
    if freshness > 1:
        freshness = 1.0
    return float(freshness)


_RE_FLAGS = re.IGNORECASE | re.MULTILINE


def _heuristic_boosts(articles: list[dict[str, Any]]) -> float:
    """Cluster-level boosts/penalty based on simple cues in title/text.

    Applies once per cluster:
    +0.1 preregistration: 'prereg' or 'registered report'
    +0.1 open code/data: 'github' or 'open data'
    +0.2 replication: 'replication'
    +0.2 policy impact: 'policy' or 'regulator'
    -0.1 no methods: across all, none of {'random', 'double-blind', 'n='}
    """
    texts: list[str] = []
    for a in articles:
        t = (a.get("title") or "") + "\n" + (a.get("text") or "")
        texts.append(t)
    blob = "\n\n".join(texts)

    boost = 0.0
    # Boosts
    if re.search(r"\bprereg\w*\b|registered report", blob, _RE_FLAGS):
        boost += 0.1
    if re.search(r"github|open data", blob, _RE_FLAGS):
        boost += 0.1
    if re.search(r"replication", blob, _RE_FLAGS):
        boost += 0.2
    if re.search(r"\bpolicy\b|regulator", blob, _RE_FLAGS):
        boost += 0.2

    # Penalty if NO method cues across all
    has_methods = re.search(r"random|double-?blind|n=", blob, _RE_FLAGS) is not None
    if not has_methods:
        boost -= 0.1
    return boost


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
        base = 0.5 * fr + 0.3 * sw + 0.2 * cs
        heur = _heuristic_boosts(arts) if arts else 0.0
        score = base + heur
        # Clamp to [0,1]
        if score < 0:
            score = 0.0
        if score > 1:
            score = 1.0
        scored.append({"cluster_id": c["cluster_id"], "score": float(score), "size": len(arts)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
