import os

from pipeline import config, embed, io
from pipeline.io import Article, db, get_embedding, init_db, upsert_article


def _setup_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=False)
    db_path = tmp_path / "pipeline.sqlite"
    monkeypatch.setattr(config, "DB_PATH", db_path, raising=False)
    monkeypatch.setattr(io, "DB_PATH", db_path, raising=False)
    io.ensure_dirs()
    init_db()


def test_generator_inputs_store_embeddings(tmp_path, monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    monkeypatch.setattr(embed, "EMBED_OFFLINE", True)
    _setup_tmp_db(tmp_path, monkeypatch)

    a1 = Article(
        article_id="a1",
        canonical_url="https://example.com/a1",
        title="t1",
        byline=None,
        published_at="2025-01-01T00:00:00Z",
        source_id="src",
        is_preprint=0,
        text="hello world",
        lang="en",
        tags=None,
        extraction_quality=1.0,
        content_hash="h1",
    )
    a2 = Article(
        article_id="a2",
        canonical_url="https://example.com/a2",
        title="t2",
        byline=None,
        published_at="2025-01-02T00:00:00Z",
        source_id="src",
        is_preprint=0,
        text="goodbye world",
        lang="en",
        tags=None,
        extraction_quality=1.0,
        content_hash="h2",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)

    hashes = (h for h in ["h1", "h2", "h1"])
    done = embed.ensure_embeddings_for_hashes(hashes)
    assert done == 2

    with db() as conn:
        assert get_embedding(conn, "h1") is not None
        assert get_embedding(conn, "h2") is not None

    # Second call should find existing embeddings and embed none
    done2 = embed.ensure_embeddings_for_hashes((h for h in ["h1", "h2"]))
    assert done2 == 0

