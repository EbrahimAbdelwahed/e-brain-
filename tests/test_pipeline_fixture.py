import os
from pathlib import Path

from pipeline.io import init_db, db
from pipeline.ingest import fetch_feeds
from pipeline.extract import extract as do_extract
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize


def test_pipeline_on_fixtures(tmp_path):
    # Fresh DB for the test
    from pipeline.config import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    # Run fetch on fixture sources (local files)
    totals = fetch_feeds(cfg_path="tests/fixtures/sources-fixture.yml")
    assert totals["feeds"] >= 1

    # Extract (fallback allowed)
    n = do_extract(parallel=2)
    assert n >= 1  # at least one Article created

    # Cluster
    clusters = do_cluster(threshold=10)
    assert len(clusters) >= 1

    # Build a minimal summaries.md in tmp_path and check for Bottom line
    summaries = summarize()
    md = ["# Summaries\n"]
    for s in summaries:
        md.append(f"\n## Cluster {s['cluster_id']}")
        for b in s["bullets"]:
            md.append(f"- {b}")
    out_md = tmp_path / "summaries.md"
    out_md.write_text("\n".join(md), encoding="utf-8")
    content = out_md.read_text(encoding="utf-8")
    assert "Bottom line:" in content

