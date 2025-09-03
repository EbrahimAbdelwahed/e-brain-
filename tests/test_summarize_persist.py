import os
import json
from pathlib import Path

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize
from pipeline.main import publish as publish_from_db


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


def test_summarize_persists_one_row_idempotent(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    _reset_db()
    _make_two_near_duplicate_articles()
    # One cluster
    do_cluster()
    # First summarize persists
    summarize()
    # Inspect DB
    with db() as conn:
        cur = conn.execute("SELECT cluster_id, tl_dr, bullets_json, citations_json, version_hash, created_at FROM summaries")
        rows1 = cur.fetchall()
    assert len(rows1) == 1
    row1 = rows1[0]
    assert isinstance(row1.get("version_hash"), str) and len(row1["version_hash"]) == 64
    created_at_1 = row1.get("created_at")
    vhash_1 = row1.get("version_hash")

    # Second summarize should not alter row (idempotent)
    summarize()
    with db() as conn:
        cur = conn.execute("SELECT cluster_id, tl_dr, bullets_json, citations_json, version_hash, created_at FROM summaries")
        rows2 = cur.fetchall()
    assert len(rows2) == 1
    row2 = rows2[0]
    assert row2.get("version_hash") == vhash_1
    assert row2.get("created_at") == created_at_1
    # bullets/citations stable
    assert row2.get("bullets_json") == row1.get("bullets_json")
    assert row2.get("citations_json") == row1.get("citations_json")


def test_publish_reads_from_db_and_writes_summaries_md(tmp_path):
    os.environ["EMBED_OFFLINE"] = "1"
    _reset_db()
    _make_two_near_duplicate_articles()
    do_cluster()
    summarize()

    out_dir = tmp_path / "run"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = publish_from_db(out_dir)
    assert len(rows) == 1
    md_path = out_dir / "summaries.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "Bottom line:" in content
    # clusters.json shape contains bullets and citations
    cj = json.loads((out_dir / "clusters.json").read_text(encoding="utf-8"))
    assert isinstance(cj, list) and len(cj) == 1
    assert isinstance(cj[0].get("bullets"), list)
    assert isinstance(cj[0].get("citations"), list)

