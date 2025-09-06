from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class DiscoveryRecord:
    # Architect contract fields
    doi: Optional[str]
    title: str
    venue: Optional[str]
    pub_date: Optional[str]  # ISO date string (YYYY-MM-DD) if available
    is_preprint: bool
    arxiv_id: Optional[str]
    pmid: Optional[str]
    pmcid: Optional[str]
    source: str  # which upstream client/source produced this record
    ingested_at: str  # ISO timestamp
    source_url: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

