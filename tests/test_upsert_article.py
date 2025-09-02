from pipeline import io
from pipeline.io import Article, init_db, db, upsert_article, fetch_articles


def test_upsert_article_duplicate_content_hash(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setattr(io, "DB_PATH", db_path)
    monkeypatch.setattr(io, "ensure_dirs", lambda: db_path.parent.mkdir(parents=True, exist_ok=True))
    init_db()
    with db() as conn:
        a1 = Article(
            article_id="a1",
            canonical_url="http://example.com/1",
            title="t1",
            byline=None,
            published_at=None,
            source_id="src",
            is_preprint=0,
            text="hello",
            lang=None,
            tags=None,
            extraction_quality=None,
            content_hash="hash",
        )
        upsert_article(conn, a1)

        a2 = Article(
            article_id="a2",
            canonical_url="http://example.com/2",
            title="t2",
            byline=None,
            published_at=None,
            source_id="src",
            is_preprint=0,
            text="hello again",
            lang=None,
            tags=None,
            extraction_quality=None,
            content_hash="hash",
        )
        upsert_article(conn, a2)

        articles = fetch_articles(conn)
        assert len(articles) == 1
        assert articles[0]["article_id"] == "a1"
