from __future__ import annotations

import datetime as dt
import json
import re
from typing import Iterable, List, Optional

import time

import http.client

from ..config import get_settings
from ..db import insert_raw_items, upsert_source_x
from ..util.logging import get_logger


logger = get_logger(__name__)


def _read_accounts_from_markdown(path: str = "accounts-to-follow.md") -> List[str]:
    handles: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # Extract a handle like @Handle from the first column of the table
                m = re.match(r"\|\s*(@[A-Za-z0-9_]+)\s*\|", line)
                if m:
                    handles.append(m.group(1))
    except FileNotFoundError:
        logger.error("accounts_file_missing")
    return sorted(set(handles))


def _x_get(path: str, bearer: str, *, retries: int = 3) -> Optional[dict]:
    """GET helper with basic retry and rate-limit backoff.

    - Logs status, host, path, and a body snippet on errors.
    - Backs off on 429 and 5xx with exponential delay.
    """
    s = get_settings()
    host = s.x_api_base or "api.twitter.com"
    attempt = 0
    backoff = 1.0
    while attempt <= retries:
        attempt += 1
        conn = http.client.HTTPSConnection(host, timeout=15)
        headers = {
            "Authorization": f"Bearer {bearer}",
            "User-Agent": "e-brain/ingest (+https://github.com/your-org/e-brain)",
            "Accept": "application/json",
        }
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except Exception as e:
            logger.error(
                "x_api_http_error",
                extra={"error": str(e), "host": host, "path": path, "attempt": attempt},
            )
            if attempt > retries:
                return None
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status == 200:
            try:
                return json.loads(data.decode("utf-8"))
            except Exception as e:
                logger.error("x_api_json_error", extra={"error": str(e)})
                return None

        body_snip = data.decode("utf-8", errors="ignore")[:500]
        # Log the error with details
        logger.error(
            "x_api_error",
            extra={
                "status": resp.status,
                "host": host,
                "path": path,
                "body": body_snip,
                "attempt": attempt,
            },
        )
        # 429 or 5xx → backoff and retry
        if resp.status == 429 or 500 <= resp.status < 600:
            if attempt > retries:
                return None
            # Respect Retry-After if present
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else backoff
            time.sleep(max(1.0, delay))
            backoff = min(backoff * 2, 30.0)
            continue
        # For 401/403/404 etc., don't keep retrying
        return None


def _username_to_id(username: str, bearer: str) -> Optional[str]:
    # usernames are without @ for the endpoint
    uname = username.lstrip("@")
    data = _x_get(f"/2/users/by/username/{uname}", bearer)
    if not data or "data" not in data:
        return None
    return data["data"].get("id")


def _user_recent_tweets(user_id: str, bearer: str, max_results: int = 5) -> list[dict]:
    # X API requires 5 <= max_results <= 100
    effective_max = max(5, min(int(max_results or 5), 100))
    params = f"max_results={effective_max}&tweet.fields=created_at,author_id,text"
    data = _x_get(f"/2/users/{user_id}/tweets?{params}", bearer)
    return data.get("data", []) if data else []


def ingest_from_accounts(accounts_md_path: str = "accounts-to-follow.md", max_per_account: int = 5) -> int:
    settings = get_settings()
    if not settings.x_bearer_token:
        logger.error("x_bearer_missing")
        return 0
    handles = _read_accounts_from_markdown(accounts_md_path)
    total_inserted = 0
    for handle in handles:
        # Resolve user id first to avoid creating source rows for invalid/protected accounts
        uid = _username_to_id(handle, settings.x_bearer_token)
        if not uid:
            logger.error("x_user_lookup_failed", extra={"handle": handle})
            continue
        source_id = upsert_source_x(handle)
        tweets = _user_recent_tweets(uid, settings.x_bearer_token, max_results=max_per_account)
        items = []
        # Respect caller's requested cap even if API requires >=5
        for tw in tweets[: max(0, int(max_per_account))]:
            created = tw.get("created_at")
            created_at = dt.datetime.fromisoformat(created.replace("Z", "+00:00")) if created else dt.datetime.utcnow()
            items.append(
                {
                    "source_type": "x",
                    "source_ref": tw.get("id"),
                    "source_id": source_id,
                    "author": handle,
                    "text": tw.get("text", "").strip(),
                    "meta": {"kind": "x_tweet", "author_id": tw.get("author_id")},
                    "created_at": created_at,
                }
            )
        total_inserted += insert_raw_items(items)
        # Small pause between accounts to be gentle with rate limits
        time.sleep(1.0)
    logger.info("ingest_completed", extra={"inserted": total_inserted, "accounts": len(handles)})
    return total_inserted
