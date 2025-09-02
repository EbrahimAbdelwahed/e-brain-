from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .io import db, fetch_articles_by_ids, fetch_cluster_members, fetch_clusters


def _first_sentence(text: str) -> str:
    for sep in (". ", "? ", "! "):
        if sep in text:
            return text.split(sep, 1)[0].strip() + sep.strip()
    return text.strip()


def _method_limit_signal(text: str) -> str | None:
    t = text.lower()
    cues = [
        ("random", "randomized design"),
        ("double-blind", "double-blind"),
        ("open-label", "open-label"),
        ("retrospective", "retrospective"),
        ("n=", "sample size reported"),
        ("mouse", "in mice"),
        ("mice", "in mice"),
        ("non-human primate", "in non-human primates"),
        ("human", "in humans"),
        ("preprint", "preprint, not peer-reviewed"),
    ]
    for key, label in cues:
        if key in t:
            return label
    return None


def _map_article(article: dict[str, Any]) -> list[str]:
    title = (article.get("title") or "").strip()
    text = (article.get("text") or "").strip()
    claim = _first_sentence(title or text)
    method = _method_limit_signal(text)
    bullets = [f"Claim/result: {claim}"]
    if method:
        bullets.append(f"Method/limit: {method}.")
    else:
        bullets.append("Method/limit: not clearly stated.")
    return bullets[:2]


def _reduce_cluster(cluster_articles: list[dict[str, Any]]) -> list[str]:
    # 3–5 bullets: what changed, note disagreements, label preprints; end with Bottom line
    bullets: list[str] = []
    titles = [a.get("title") or "" for a in cluster_articles]
    preprints = sum(1 for a in cluster_articles if int(a.get("is_preprint") or 0) == 1)
    outlets = [a.get("canonical_url") or "" for a in cluster_articles]
    domains = [o.split("/")[2] if "//" in o else o for o in outlets if o]
    dom_top = ", ".join([d for d, _ in Counter(domains).most_common(2)])

    bullets.append(f"What changed: {titles[0][:160]}".rstrip(".") + ".")
    if preprints:
        bullets.append(f"Preprints: {preprints} in this cluster; interpret cautiously.")
    if dom_top:
        bullets.append(f"Coverage: {dom_top}.")
    # Disagreements heuristic: differing titles length variance
    if len(set(titles)) > 1:
        bullets.append("Disagreements: reports vary; check methods and sample sizes.")
    bullets.append("Bottom line: evidence-first reading over hype; see citations.")
    return bullets[:5]


def _citations(cluster_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in cluster_articles:
        url = a.get("canonical_url") or ""
        outlet = url.split("/")[2] if "//" in url else url
        out.append({
            "title": a.get("title"),
            "outlet": outlet,
            "url": url,
            "date": a.get("published_at"),
        })
    return out


def summarize(logger: logging.Logger | None = None) -> list[dict[str, Any]]:
    with db() as conn:
        clusters = fetch_clusters(conn)
    if not clusters:
        if logger:
            logger.info("No clusters to summarize.")
        return []
    results: list[dict[str, Any]] = []
    for c in clusters:
        with db() as conn:
            members = fetch_cluster_members(conn, c["cluster_id"])  # list of article_ids
            arts = fetch_articles_by_ids(conn, members)
        map_bullets = [b for a in arts for b in _map_article(a)]
        red_bullets = _reduce_cluster(arts)
        # Include per-article claim/method bullets after the cluster-level summary
        bullets = red_bullets + map_bullets
        citations = _citations(arts)
        results.append(
            {
                "cluster_id": c["cluster_id"],
                "bullets": bullets,
                "delta": {"articles": len(arts)},
                "citations": citations,
                "labeled_preprint": any(int(a.get("is_preprint") or 0) == 1 for a in arts),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    if logger:
        logger.info("Summarized %d clusters", len(results))
    return results

