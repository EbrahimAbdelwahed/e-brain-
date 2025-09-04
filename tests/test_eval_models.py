import json
import os
from pathlib import Path

import pytest

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster


def _reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def _make_cluster_two_items():
    a1 = Article(
        article_id="e1",
        canonical_url="https://example.com/e1",
        title="Neuron firing patterns updated",
        byline=None,
        published_at="2025-09-01T00:00:00Z",
        source_id="example-src",
        is_preprint=0,
        text="Researchers report updated neuron firing patterns in mice; n=20.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="eh1",
    )
    a2 = Article(
        article_id="e2",
        canonical_url="https://example.com/e2",
        title="Updated neuron firing patterns",
        byline=None,
        published_at="2025-09-01T01:00:00Z",
        source_id="example-src",
        is_preprint=0,
        text="Updated neuron firing patterns in mice!",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="eh2",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)


def _find_run_dir(base: Path) -> Path:
    dirs = [p for p in base.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def test_eval_models_produces_artifacts_and_no_db_mutation(tmp_path, monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "test-key"  # gate for LLM branch in summarize
    _reset_db()
    _make_cluster_two_items()
    do_cluster()

    # Snapshot summaries table before
    with db() as conn:
        before = list(conn.execute("SELECT * FROM summaries").fetchall())

    # Monkeypatch provider to return different outputs per model
    def fake_chat(model: str, **kwargs):  # type: ignore
        return (
            f"Lead: {model} lead.\n"
            f"- Bullet A {model}.\n"
            f"- Bottom line: verdict {model}.\n"
        )

    monkeypatch.setattr("pipeline.llm.generate_chat", fake_chat)

    from pipeline.__main__ import eval_models as cli_eval_models

    cli_eval_models(out=tmp_path, models="m1,m2", seed=123, log_level="INFO", since=None, dry_run=False)

    run_dir = _find_run_dir(tmp_path)
    eval_dir = run_dir / "eval"
    assert eval_dir.exists()
    m1 = (eval_dir / "m1.md").read_text(encoding="utf-8")
    m2 = (eval_dir / "m2.md").read_text(encoding="utf-8")
    assert m1 != m2  # different per model
    comp = (eval_dir / "compare.md").read_text(encoding="utf-8")
    assert "## Cluster" in comp
    assert "### m1" in comp and "### m2" in comp
    assert "Bottom line:" in comp

    # eval_report.json exists and records models and params
    report = json.loads((run_dir / "eval_report.json").read_text(encoding="utf-8"))
    assert report.get("models") == ["m1", "m2"]
    params = report.get("params") or {}
    assert "temperature" in params and "top_p" in params

    # DB summaries unchanged
    with db() as conn:
        after = list(conn.execute("SELECT * FROM summaries").fetchall())
    assert after == before


def test_eval_models_integration_with_fixtures(tmp_path, monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    _reset_db()

    # End-to-end using fixtures (offline)
    from pipeline.ingest import fetch_feeds
    from pipeline.extract import extract as do_extract

    totals = fetch_feeds(cfg_path="tests/fixtures/sources-fixture.yml")
    assert totals["feeds"] >= 1
    n = do_extract(parallel=2)
    assert n >= 1
    do_cluster()

    # Monkeypatch provider stub
    def fake_chat(model: str, **kwargs):  # type: ignore
        return (
            f"Lead: fixture {model}.\n"
            f"- One.\n"
            f"- Bottom line: ok {model}.\n"
        )

    monkeypatch.setattr("pipeline.llm.generate_chat", fake_chat)

    from pipeline.__main__ import eval_models as cli_eval_models

    cli_eval_models(out=tmp_path, models="fx1,fx2", seed=None, log_level="INFO", since=None, dry_run=False)
    run_dir = _find_run_dir(tmp_path)
    eval_dir = run_dir / "eval"
    assert (eval_dir / "fx1.md").exists() and (eval_dir / "fx2.md").exists()
    assert (eval_dir / "compare.md").exists()

