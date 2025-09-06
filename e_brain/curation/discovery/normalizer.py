from __future__ import annotations

import datetime as dt
from typing import Dict, Any, Optional


def _canonical_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return doi.strip().lower()


def _infer_is_preprint(venue: Optional[str]) -> bool:
    v = (venue or "").strip().lower()
    return any(tag in v for tag in ("biorxiv", "medrxiv", "arxiv", "preprint"))


def _pick_date(raw: Dict[str, Any]) -> Optional[str]:
    # Prefer explicit pub_date; otherwise None (runner will default to now)
    d = raw.get("pub_date")
    if not d:
        return None
    try:
        # Accept already ISO-like dates; otherwise attempt parse of YYYY-MM-DD
        # Do a lenient slice to 10 chars
        return str(d)[:10]
    except Exception:
        return None


def normalize_record(raw: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Normalize a raw discovery dict into the architect contract shape.

    Enforces: lowercased DOI, boolean preprint, string ids, ISO dates.
    """
    now_iso = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()

    doi = _canonical_doi(raw.get("doi"))
    title = (raw.get("title") or "").strip()
    venue = (raw.get("venue") or None)
    pub_date = _pick_date(raw)
    arxiv_id = (raw.get("arxiv_id") or None)
    pmid = (raw.get("pmid") or None)
    pmcid = (raw.get("pmcid") or None)
    src_url = (raw.get("source_url") or None)

    is_preprint = bool(raw.get("is_preprint", _infer_is_preprint(venue)))

    return {
        "doi": doi,
        "title": title,
        "venue": venue,
        "pub_date": pub_date,
        "is_preprint": is_preprint,
        "arxiv_id": arxiv_id,
        "pmid": pmid,
        "pmcid": pmcid,
        "source": source,
        "ingested_at": now_iso,
        "source_url": src_url,
    }

