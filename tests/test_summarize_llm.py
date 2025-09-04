import os
import json

from pipeline.io import Article, db, init_db, upsert_article
from pipeline.config import DB_PATH
from pipeline.cluster import cluster as do_cluster
from pipeline.summarize import summarize


def _reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def _make_cluster(preprint: bool = True):
    a1 = Article(
        article_id="a1",
        canonical_url="https://example.com/same",
        title="Study on hippocampal memory",
        byline=None,
        published_at="2025-09-01T00:00:00Z",
        source_id="example-src",
        is_preprint=1 if preprint else 0,
        text="Preprint reports improved memory consolidation in mice; n=24; optogenetics.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h1",
    )
    a2 = Article(
        article_id="a2",
        canonical_url="https://example.com/same",
        title="Memory consolidation improved via optogenetics",
        byline=None,
        published_at="2025-09-01T01:00:00Z",
        source_id="example-src",
        is_preprint=1 if preprint else 0,
        text="Authors claim memory consolidation improved using optogenetics; randomized; n=24.",
        lang="en",
        tags=None,
        extraction_quality=0.9,
        content_hash="h2",
    )
    with db() as conn:
        upsert_article(conn, a1)
        upsert_article(conn, a2)


def test_llm_guardrails_bottom_line_and_citations(monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    os.environ["SUMMARIZE_USE_LLM"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    _reset_db()
    _make_cluster(preprint=True)
    do_cluster()

    # Monkeypatch provider to return deterministic text
    sample = (
        "Lead: New receipts on memory consolidation.\n"
        "- Guardrail: preprint; may change post-review.\n"
        "- Findings: small n, randomized.\n"
        "- Bottom line: promising but needs replication.\n"
    )

    def fake_chat(**kwargs):  # type: ignore
        return sample

    monkeypatch.setattr("pipeline.llm.generate_chat", fake_chat)

    results = summarize()
    assert len(results) >= 1
    r0 = results[0]
    bullets = r0["bullets"]
    joined = "\n".join(bullets)
    assert "Bottom line:" in joined
    assert "preprint; may change post-review" in joined
    assert isinstance(r0.get("citations"), list) and len(r0["citations"]) >= 1


def test_llm_called_once_with_caching(monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    os.environ["SUMMARIZE_USE_LLM"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    _reset_db()
    _make_cluster(preprint=False)
    do_cluster()

    sample = (
        "Lead: Update on consolidation.\n"
        "- Bullet 1.\n"
        "- Bottom line: stable.\n"
    )
    calls = {"n": 0}

    def fake_chat(**kwargs):  # type: ignore
        calls["n"] += 1
        return sample

    monkeypatch.setattr("pipeline.llm.generate_chat", fake_chat)

    # First run -> calls provider
    summarize(model="moonshotai/kimi-k2")
    # Second run with same inputs/model -> should hit cache and not call provider again
    summarize(model="moonshotai/kimi-k2")
    assert calls["n"] == 1


def test_llm_cache_miss_on_model_change(monkeypatch):
    os.environ["EMBED_OFFLINE"] = "1"
    os.environ["SUMMARIZE_USE_LLM"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "test-key"
    _reset_db()
    _make_cluster(preprint=False)
    do_cluster()

    sample = (
        "Lead: Model compare.\n"
        "- Bullet.\n"
        "- Bottom line: ok.\n"
    )
    calls = {"n": 0}

    def fake_chat(**kwargs):  # type: ignore
        calls["n"] += 1
        return sample

    monkeypatch.setattr("pipeline.llm.generate_chat", fake_chat)

    summarize(model="moonshotai/kimi-k2")
    summarize(model="other/model")
    assert calls["n"] == 2
