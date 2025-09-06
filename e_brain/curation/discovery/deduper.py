from __future__ import annotations

from typing import Dict, Any, Iterable, List, Set, Tuple


def _identity_key(rec: Dict[str, Any]) -> Tuple[str, str] | None:
    # Priority: doi → arxiv_id → pmid/pmcid
    doi = rec.get("doi")
    if doi:
        return ("doi", str(doi))
    arxiv_id = rec.get("arxiv_id")
    if arxiv_id:
        return ("arxiv_id", str(arxiv_id))
    pmid = rec.get("pmid")
    if pmid:
        return ("pmid", str(pmid))
    pmcid = rec.get("pmcid")
    if pmcid:
        return ("pmcid", str(pmcid))
    return None


def dedupe(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedupe records using key order: doi → arxiv_id → pmid/pmcid.

    Keeps the first record encountered for a given identity.
    """
    seen: Set[Tuple[str, str]] = set()
    result: List[Dict[str, Any]] = []
    for r in records:
        key = _identity_key(r)
        if not key:
            # Items without any identifier pass through independently
            result.append(r)
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(r)
    return result

