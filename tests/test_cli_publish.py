import json
import os
from pathlib import Path

import pytest

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize as do_summarize
from pipeline.ingest import fetch_feeds
from pipeline.extract import extract as do_extract


def _reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def _make_two_near_duplicate_articles():
    a1 = Article(
        article_id="s1",
        canonical_url="https://example.com/s1",
        title="Breakthrough in memory consolidation",
        byline=None,
        published_at="2025-09-01T00:00:00Z",
        source_id="example-src",
        is_preprint=0,
        text="Researchers report a breakthrough in memory consolidation using optogenetics.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="sh1",
    )
    a2 = Article(
        article_id="s2",
        canonical_url="https://example.com/s2",
        title="Memory consolidation breakthrough",
        byline=None,
        published_at="2025-09-01T01:00:00Z",
        source_id="example-src",
        is_preprint=0,
        text="Researchers report a breakthrough in memory consolidation using optogenetics!",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="sh2",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)


def _find_run_dir(base: Path) -> Path:
    dirs = [p for p in base.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_cli_publish_does_not_call_summarize_when_summaries_exist(tmp_path, monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    _reset_db()
    _make_two_near_duplicate_articles()
    do_cluster()
    # Persist summaries once
    do_summarize()

    # Make summarize blow up if called again
    def _boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("summarize should not be called by CLI publish")

    monkeypatch.setattr("pipeline.summarize.summarize", _boom, raising=True)

    from pipeline.__main__ import publish as cli_publish

    # Run CLI publish into tmp_path
    cli_publish(out=tmp_path, log_level="INFO", since=None, dry_run=False)
    run_dir = _find_run_dir(tmp_path)
    md = run_dir / "summaries.md"
    cj = run_dir / "clusters.json"
    assert md.exists() and cj.exists()
    content = md.read_text(encoding="utf-8")
    assert "Bottom line:" in content
    data = json.loads(cj.read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) >= 1
    assert isinstance(data[0].get("bullets"), list)
    assert isinstance(data[0].get("citations"), list)


def test_cli_publish_empty_db_noop(tmp_path):
    _reset_db()
    from pipeline.__main__ import publish as cli_publish

    cli_publish(out=tmp_path, log_level="INFO", since=None, dry_run=False)
    run_dir = _find_run_dir(tmp_path)
    # No files written
    assert not (run_dir / "summaries.md").exists()
    assert not (run_dir / "clusters.json").exists()
    # Log contains clear message
    log_path = run_dir / "logs" / "run.log"
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "No summaries in DB to publish." in log_text


def test_cli_publish_integration_with_fixtures(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    _reset_db()
    # End-to-end on fixtures (no network)
    totals = fetch_feeds(cfg_path="tests/fixtures/sources-fixture.yml")
    assert totals["feeds"] >= 1
    n = do_extract(parallel=2)
    assert n >= 1
    cs = do_cluster()
    assert len(cs) >= 1
    do_summarize()

    from pipeline.__main__ import publish as cli_publish

    cli_publish(out=tmp_path, log_level="INFO", since=None, dry_run=False)
    run_dir = _find_run_dir(tmp_path)
    md = run_dir / "summaries.md"
    cj = run_dir / "clusters.json"
    assert md.exists() and cj.exists()
    content = md.read_text(encoding="utf-8")
    assert "Bottom line:" in content
