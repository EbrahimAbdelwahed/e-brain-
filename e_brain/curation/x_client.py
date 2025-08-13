from __future__ import annotations

import datetime as dt
import json
import re
from typing import Iterable, List, Optional

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


def _x_get(path: str, bearer: str) -> Optional[dict]:
    # Minimal HTTP GET using stdlib to avoid extra deps; expects JSON response.
    conn = http.client.HTTPSConnection("api.x.com")
    headers = {"Authorization": f"Bearer {bearer}"}
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    if resp.status != 200:
        logger.error("x_api_error", extra={"status": resp.status, "path": path})
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        logger.error("x_api_json_error")
        return None


def _username_to_id(username: str, bearer: str) -> Optional[str]:
    # usernames are without @ for the endpoint
    uname = username.lstrip("@")
    data = _x_get(f"/2/users/by/username/{uname}", bearer)
    if not data or "data" not in data:
        return None
    return data["data"].get("id")


def _user_recent_tweets(user_id: str, bearer: str, max_results: int = 5) -> list[dict]:
    params = f"max_results={max_results}&tweet.fields=created_at,author_id,text"
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
        source_id = upsert_source_x(handle)
        uid = _username_to_id(handle, settings.x_bearer_token)
        if not uid:
            continue
        tweets = _user_recent_tweets(uid, settings.x_bearer_token, max_results=max_per_account)
        items = []
        for tw in tweets:
            created = tw.get("created_at")
            created_at = dt.datetime.fromisoformat(created.replace("Z", "+00:00")) if created else dt.datetime.utcnow()
            items.append(
                {
                    "source_type": "x",
                    "source_ref": tw.get("id"),
                    "source_id": source_id,
                    "author": handle,
                    "text": tw.get("text", "").strip(),
                    "created_at": created_at,
                }
            )
        total_inserted += insert_raw_items(items)
    logger.info("ingest_completed", extra={"inserted": total_inserted, "accounts": len(handles)})
    return total_inserted

