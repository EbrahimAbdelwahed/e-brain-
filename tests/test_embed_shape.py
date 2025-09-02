import os

from pipeline.embed import embed_text


def test_embed_shape_offline_stub():
    os.environ["EMBED_OFFLINE"] = "1"
    vec = embed_text("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1536
    # normalized
    s = sum(x * x for x in vec) ** 0.5
    assert 0.9 < s < 1.1

