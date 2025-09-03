from __future__ import annotations

from typing import Dict, Tuple
from urllib.parse import urlsplit, urlunsplit
from urllib import robotparser

from .io import http_get_bytes


# In-process memoization of parsed robots per host keyed by cache validators
# key: host, value: ((etag, last_modified), RobotFileParser)
_ROBOTS_MEMO: Dict[str, Tuple[Tuple[str | None, str | None], robotparser.RobotFileParser]] = {}


def _robots_url_from(url: str) -> tuple[str, str]:
    """Return (host, robots_url) for an absolute URL.

    If the URL is not http(s), returns ("", "").
    """
    sp = urlsplit(url)
    if sp.scheme not in {"http", "https"}:
        return "", ""
    host = sp.netloc
    robots_url = urlunsplit((sp.scheme, host, "/robots.txt", "", ""))
    return host, robots_url


def parse_robots_text(base_url: str, text: str) -> robotparser.RobotFileParser:
    """Helper to build a RobotFileParser from raw robots.txt text.

    Useful for tests where we want to feed sample robots directives.
    """
    host, robots_url = _robots_url_from(base_url)
    rp = robotparser.RobotFileParser()
    if robots_url:
        rp.set_url(robots_url)
    rp.parse(text.splitlines())
    return rp


def robots_allowed(url: str, user_agent: str) -> bool:
    """Return whether fetching `url` is allowed for `user_agent`.

    - Builds robots.txt URL for the host
    - Fetches via cached HTTP (ETag/Last-Modified)
    - Parses using urllib.robotparser
    - Memoizes the parsed result keyed by (host, etag, last_modified)
    """
    host, robots_url = _robots_url_from(url)
    if not robots_url:
        # file:// and others: allow by default
        return True

    try:
        status, content, headers = http_get_bytes(robots_url)
    except Exception:
        # If robots cannot be fetched, be permissive (common practice)
        return True

    etag = headers.get("ETag")
    last_mod = headers.get("Last-Modified")
    cache_key = (etag, last_mod)

    # On 304 use memo if present
    if status == 304 and host in _ROBOTS_MEMO:
        rp = _ROBOTS_MEMO[host][1]
        return rp.can_fetch(user_agent, url)

    # On 200 with body, (re)parse
    if status == 200 and content is not None:
        try:
            text = content.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        rp = parse_robots_text(url, text)
        _ROBOTS_MEMO[host] = (cache_key, rp)
        return rp.can_fetch(user_agent, url)

    # Other statuses: if we have a memo, use it, otherwise allow
    if host in _ROBOTS_MEMO:
        rp = _ROBOTS_MEMO[host][1]
        return rp.can_fetch(user_agent, url)
    return True

