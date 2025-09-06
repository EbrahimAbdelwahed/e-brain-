from e_brain.curation.discovery.deduper import dedupe


def test_deduper_prefers_first_by_identity():
    items = [
        {"doi": "10.1/abc", "title": "A"},
        {"doi": "10.1/abc", "title": "B"},
        {"arxiv_id": "arXiv:1234.5678", "title": "C"},
        {"arxiv_id": "arXiv:1234.5678", "title": "D"},
        {"pmid": "999", "title": "E"},
        {"pmcid": "PMC123", "title": "F"},
        {"title": "G"},  # no identifiers
        {"title": "H"},  # no identifiers (kept independently)
    ]

    out = dedupe(items)
    titles = [r.get("title") for r in out]
    # Keeps first A for DOI, first C for arXiv, first E for PMID, keeps both G and H
    assert titles == ["A", "C", "E", "G", "H"]

