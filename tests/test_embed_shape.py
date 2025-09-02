import os

import pipeline.embed as embed


def test_embed_shape_offline_stub(monkeypatch):
    monkeypatch.setenv("EMBED_OFFLINE", "1")
    vec = embed.embed_text("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1536
    # normalized
    s = sum(x * x for x in vec) ** 0.5
    assert 0.9 < s < 1.1


def test_embed_runtime_toggle(monkeypatch):
    monkeypatch.setenv("EMBED_OFFLINE", "1")
    vec_offline = embed.embed_text("hello world")

    called = {"called": False}

    def fake_embed_openai_chunks(chunks, model=embed.EMBED_MODEL):
        called["called"] = True
        return [[0.0] * embed.EMBED_DIMS for _ in chunks]

    monkeypatch.setattr(embed, "_embed_openai_chunks", fake_embed_openai_chunks)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("EMBED_OFFLINE", "0")
    vec_online = embed.embed_text("hello world")

    assert called["called"]
    assert vec_online == [0.0] * embed.EMBED_DIMS
    assert vec_online != vec_offline

