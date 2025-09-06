from __future__ import annotations

import datetime as dt
from typing import Dict, Any, List

from .clients.base import DiscoveryClient, DummyStaticClient
from .normalizer import normalize_record
from .deduper import dedupe
from .emitter import write_ndjson, write_metrics
from .ipfs import pin_dataset, try_fetch_content

from ...db import insert_raw_items
from ...util.logging import get_logger


logger = get_logger(__name__)


def _to_raw_item(rec: Dict[str, Any], text: str, created_at: dt.datetime) -> Dict[str, Any]:
    return {
        "source_type": "doi",
        "source_ref": rec.get("doi") or rec.get("arxiv_id") or rec.get("pmid") or rec.get("pmcid") or rec.get("title")[:120],
        "source_id": None,
        "author": rec.get("venue"),
        "text": text,
        "meta": rec,
        "created_at": created_at,
    }


def run_discovery(
    window_days: int = 60,
    out_dir: str = "artifacts",
    ipfs_fetch: bool = False,
    store_to_db: bool = True,
) -> Dict[str, Any]:
    now = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    window_end = now
    window_start = now - dt.timedelta(days=max(1, int(window_days)))

    # Placeholder clients for M1; replace in M2 with real clients
    clients: List[DiscoveryClient] = [DummyStaticClient("seed")]  # scaffold

    raw_records: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "clients": [],
    }

    for c in clients:
        recs = list(c.fetch(window_start, window_end))
        raw_records.extend(recs)
        cm = c.metrics()
        metrics["clients"].append(cm)

    # Normalize and dedupe
    normalized = [normalize_record(r, source=r.get("source") or "unknown") for r in raw_records]
    deduped = dedupe(normalized)

    # Optional IPFS pin + content fetch
    fetched_texts: Dict[str, str] = {}
    if ipfs_fetch:
        pin_dataset()
        for r in deduped:
            doi = r.get("doi")
            if not doi:
                continue
            content = try_fetch_content(doi)
            if content:
                fetched_texts[doi] = content

    # Map to raw_items
    items = []
    for r in deduped:
        # created_at: prefer pub_date, else now
        if r.get("pub_date"):
            try:
                y, m, d = map(int, str(r["pub_date"])[:10].split("-"))
                created_at = dt.datetime(y, m, d, tzinfo=dt.timezone.utc)
            except Exception:
                created_at = now
        else:
            created_at = now

        # text: fetched or fallback
        text = None
        doi = r.get("doi")
        if doi and doi in fetched_texts:
            text = fetched_texts[doi]
        if not text:
            text = f"{r.get('title', '').strip()} — DOI: {doi or (r.get('arxiv_id') or r.get('pmid') or r.get('pmcid') or 'n/a')}"

        items.append(_to_raw_item(r, text=text, created_at=created_at))

    # Emit artifacts
    artifact_path, artifact_count = write_ndjson(deduped, out_dir)
    metrics.update({
        "emitted_count": artifact_count,
        "artifact_path": artifact_path,
        "normalized_count": len(normalized),
        "deduped_count": len(deduped),
    })
    metrics_path = write_metrics(metrics, out_dir)

    inserted = 0
    if store_to_db:
        inserted = insert_raw_items(items)

    logger.info(
        "discovery_completed",
        extra={
            "inserted": inserted,
            "artifacts": artifact_path,
            "metrics": metrics_path,
            "window_days": window_days,
        },
    )
    return {
        "inserted": inserted,
        "artifact_path": artifact_path,
        "metrics_path": metrics_path,
        "counts": {
            "raw": len(raw_records),
            "normalized": len(normalized),
            "deduped": len(deduped),
        },
    }

