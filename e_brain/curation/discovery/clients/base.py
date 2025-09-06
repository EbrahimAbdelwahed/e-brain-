from __future__ import annotations

import abc
import datetime as dt
from typing import Iterable, Dict, Any


class DiscoveryClient(abc.ABC):
    """Abstract client for DOI discovery.

    Implementations should yield raw dicts that will be normalized by the
    normalizer. At minimum include any of: doi, title, venue, ids, pub date.
    """

    @abc.abstractmethod
    def fetch(self, window_start: dt.datetime, window_end: dt.datetime) -> Iterable[Dict[str, Any]]:
        raise NotImplementedError

    def metrics(self) -> Dict[str, Any]:
        return {}


class DummyStaticClient(DiscoveryClient):
    """Temporary static client that emits a few mocked records for M1 scaffolding."""

    def __init__(self, source_name: str = "dummy") -> None:
        self._source = source_name
        self._count = 0

    def fetch(self, window_start: dt.datetime, window_end: dt.datetime) -> Iterable[Dict[str, Any]]:
        self._count = 5
        # A small, deterministic set with mixed identifiers
        base_date = window_end.date().isoformat()
        return [
            {
                "doi": "10.1038/nn.12345",
                "title": "Neural Circuit Dynamics in Learning",
                "venue": "Nature Neuroscience",
                "pub_date": base_date,
                "arxiv_id": None,
                "pmid": None,
                "pmcid": None,
                "source": self._source,
                "source_url": "https://doi.org/10.1038/nn.12345",
            },
            {
                "doi": None,
                "title": "Transformer Models for Brain Signals",
                "venue": "arXiv",
                "pub_date": base_date,
                "arxiv_id": "arXiv:2401.00001",
                "pmid": None,
                "pmcid": None,
                "source": self._source,
                "source_url": "https://arxiv.org/abs/2401.00001",
            },
            {
                "doi": None,
                "title": "Glial cells and synaptic modulation",
                "venue": "bioRxiv",
                "pub_date": base_date,
                "arxiv_id": None,
                "pmid": "39200001",
                "pmcid": None,
                "source": self._source,
                "source_url": None,
            },
            {
                # Duplicate of first by DOI to test dedupe
                "doi": "10.1038/nn.12345",
                "title": "Neural Circuit Dynamics in Learning (Version 2)",
                "venue": "Nature Neuroscience",
                "pub_date": base_date,
                "arxiv_id": None,
                "pmid": None,
                "pmcid": None,
                "source": self._source,
                "source_url": "https://doi.org/10.1038/nn.12345",
            },
            {
                # Duplicate of second by arXiv ID
                "doi": None,
                "title": "Transformer Models for Brain Signals (rev)",
                "venue": "arXiv",
                "pub_date": base_date,
                "arxiv_id": "arXiv:2401.00001",
                "pmid": None,
                "pmcid": None,
                "source": self._source,
                "source_url": "https://arxiv.org/abs/2401.00001",
            },
        ]

    def metrics(self) -> Dict[str, Any]:
        return {"emitted": self._count, "source": self._source}

