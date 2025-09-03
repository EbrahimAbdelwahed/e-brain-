from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .io import db, fetch_articles_by_ids, fetch_cluster_members, fetch_summaries, mark_published
from .rank import score_clusters


def _build_publish_rows() -> list[dict[str, Any]]:
    with db() as conn:
        summaries = fetch_summaries(conn)
    if not summaries:
        return []
    # Rank scores
    scores = score_clusters()
    score_map = {s["cluster_id"]: s for s in scores}

    # Inflate rows to previous shape
    rows: list[dict[str, Any]] = []
    for s in summaries:
        cluster_id = s["cluster_id"]
        # Rehydrate bullets/citations
        try:
            bullets = json.loads(s.get("bullets_json") or "[]")
        except Exception:  # noqa: BLE001
            bullets = []
        try:
            citations = json.loads(s.get("citations_json") or "[]")
        except Exception:  # noqa: BLE001
            citations = []
        # Compute delta + labeled_preprint from current members
        with db() as conn:
            members = fetch_cluster_members(conn, cluster_id)
            arts = fetch_articles_by_ids(conn, members)
        labeled_preprint = any(int(a.get("is_preprint") or 0) == 1 for a in arts)
        delta = {"articles": len(arts)}
        base = {
            "cluster_id": cluster_id,
            "bullets": bullets,
            "delta": delta,
            "citations": citations,
            "labeled_preprint": labeled_preprint,
            "created_at": s.get("created_at"),
        }
        sc = score_map.get(cluster_id, {"score": 0.0, "size": 0})
        rows.append({**base, **sc})
    rows.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return rows


def publish(out_dir: Path, *, dry_run: bool = False, logger: logging.Logger | None = None) -> list[dict[str, Any]]:
    """Publish ranked summaries from persisted DB rows to files.

    Writes `clusters.json` and `summaries.md` in `out_dir`, matching previous shapes.
    Returns the sorted rows used for publishing.
    """
    rows = _build_publish_rows()
    if not rows:
        if logger:
            logger.info("No summaries in DB to publish.")
        return []
    # clusters.json
    clusters_json = Path(out_dir) / "clusters.json"
    data = rows
    if not dry_run:
        clusters_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # summaries.md (unchanged shape for bullets/citations)
    md_lines = ["# E-Brain Bot Summaries\n"]
    for r in rows:
        md_lines.append(
            f"\n## Cluster {r['cluster_id']} — score {r.get('score', 0.0):.3f}, size {r.get('size', 0)}"
        )
        for b in r["bullets"]:
            md_lines.append(f"- {b}")
        md_lines.append("\nCitations:")
        for c in r["citations"]:
            md_lines.append(f"- [{c.get('title')}]({c.get('url')}) — {c.get('outlet')} — {c.get('date')}")
    if not dry_run:
        (Path(out_dir) / "summaries.md").write_text("\n".join(md_lines), encoding="utf-8")

    # Mark published timestamp
    try:
        with db() as conn:
            mark_published(conn, [r["cluster_id"] for r in rows])
    except Exception:  # noqa: BLE001
        # Non-fatal if we cannot mark published
        pass

    if logger:
        logger.info("Publish: %d clusters -> %s", len(rows), out_dir)
    return rows

