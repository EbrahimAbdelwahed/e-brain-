import os


def test_obs_span_noop_context_manager(monkeypatch):
    # Ensure no Langfuse env is set
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    from pipeline.obs import obs_span, OBS_ENABLED

    assert OBS_ENABLED is False
    # Should be usable as a context manager without raising and without network
    with obs_span("unit-test", {"foo": "bar", "n": 1}) as span:
        span.set({"extra": 2})
        x = 1 + 2
        assert x == 3


def test_summarize_path_unaffected_without_obs_env(monkeypatch):
    # No Langfuse env set -> no-op instrumentation
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    from pipeline.summarize import summarize

    # With an empty DB, summarize returns [] (unchanged baseline behavior)
    res = summarize()
    assert isinstance(res, list)
    assert len(res) == 0

