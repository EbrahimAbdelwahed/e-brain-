import os
from pathlib import Path

import pytest

from pipeline.io import init_db, db
from pipeline.ingest import fetch_feeds
from pipeline.extract import extract as do_extract


@pytest.fixture(autouse=True)
def clean_db():
    # Fresh DB before each test
    from pipeline.config import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    yield


def test_extract_respects_robots_and_avoids_network(monkeypatch):
    # Seed raws from fixture feeds (file://)
    fetch_feeds(cfg_path="tests/fixtures/sources-fixture.yml")

    # Deny all via robots helper
    monkeypatch.setattr("pipeline.robots.robots_allowed", lambda url, ua: False)

    # Ensure no network fetch for articles when denied
    def _no_fetch(url: str, *args, **kwargs):
        if url.startswith("http://") or url.startswith("https://"):
            raise AssertionError("Should not fetch network for disallowed URL")
        return 200, b"", {}

    monkeypatch.setattr("pipeline.io.http_get_bytes", _no_fetch)

    n = do_extract(parallel=2)
    assert n >= 1  # Fallback article created


def test_extract_allows_but_falls_back_offline(monkeypatch):
    # Fresh DB
    from pipeline.config import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    fetch_feeds(cfg_path="tests/fixtures/sources-fixture.yml")

    # Allow via robots
    monkeypatch.setattr("pipeline.robots.robots_allowed", lambda url, ua: True)

    # Simulate offline fetch error for article pages
    class _Err(Exception):
        pass

    def _offline(url: str, *args, **kwargs):
        if url.startswith("http://") or url.startswith("https://"):
            raise _Err("offline")
        return 200, b"", {}

    monkeypatch.setattr("pipeline.io.http_get_bytes", _offline)

    n = do_extract(parallel=2)
    assert n >= 1  # Fallback still works when offline

