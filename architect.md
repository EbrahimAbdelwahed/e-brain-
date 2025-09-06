
# ARCHITECT.md — Discovery→DOI Pipeline (Neuro + Neuro/AI)

> This file is the **single source of truth** for the “Architect” Codex instance.
> Mission: Orchestrate sub-agents to deliver a **reliable, automated DOI discovery loop** that finds ≥50 relevant works/week from the last 60 days across brain sciences, neuroscience, computational neuroscience, AI/ML, and adjacent biomedical domains—then hands those DOIs to the existing content retriever via **IPFS**.

---

## 0) Intent Recap (what “good” looks like)

* **Goal:** A low-cost, maintainable pipeline that **discovers** relevant recent publications and emits a **deduped DOI list** weekly (Europe/Rome timezone).
* **Scope:** Peer-reviewed journals (preferred) + preprints (acceptable), including neuro-adjacent ML/AI venues.
* **Hand-off:** Our downstream stack already fetches full content by DOI from a copyright-compliant database via **IPFS**. We must output clean identifiers + minimal metadata.
* **Target:** **≥50 unique DOIs/week** (rolling 60-day window).
* **Style:** MVP-first, cluster-centric, citations-first, **serverless/lightweight**, aggressively cached, observable, idempotent.

---

## 1) Operating Principles (apply to every task)

* **MVP-first:** ship end-to-end discovery → NDJSON DOI list → IPFS fetch path verified. Iterate.
* **RSS/API-first ingestion;** respect robots/ToS; no brittle HTML scraping.
* **Cluster-centric:** dedupe by DOI → arXiv ID → PMID/PMCID; unify versions (preprint vs. published).
* **Citations-first:** always preserve source identifiers; label `is_preprint`.
* **Lean ops:** event-driven jobs (cron + queues), retry with backoff, DLQ.
* **Cost control:** cache responses; cap tokens; prefer free/open APIs.
* **Observability:** metrics (per-source counts, RPS, error rates), traces, alerts on <50 DOIs or source failure.
* **Europe/Rome** schedule; explicit absolute dates in logs.

---

## 2) High-Level Architecture

**Stages:** Ingest → Normalize/Extract → Canonicalize → Cluster/Dedupe → Emit DOI List → IPFS-trigger (optional smoke test) → Publish/Notify → Observe

**Core sources (union, then dedupe):**

* **Crossref** (DOI authority; `type:journal-article`, date filters, cursor deep-paging)
* **Europe PMC** (PubMed/PMC + many preprints; biomedical focus; `HAS_DOI`, `PUB_TYPE`)
* **OpenAlex** (cross-disciplinary coverage; concept filters; `has_doi:true`)
* **PubMed E-utilities** (PMIDs→DOI enrichment/verification)
* **Preprints:** arXiv (neuro/AI categories), bioRxiv/medRxiv (JSON APIs)
* **CS/ML venues helper:** DBLP (fill gaps; backfill DOIs via Crossref/OpenAlex)

**Downstream (already exists):**

* **IPFS content retriever**: use `ipfs pin add /ipns/libstc.cc/dois` to fetch content **by DOI**. We only need to supply a reliable DOI list; retriever resolves content.

---

## 3) Data Contracts

### 3.1 Output record (one per item)

```
{
  "doi": "10.1038/s41593-025-XXXX-X",          // lowercase, canonicalized
  "title": "string",
  "venue": "string",                           // container-title / journal
  "pub_date": "YYYY-MM-DD",                    // earliest online/print
  "is_preprint": false,                        // true for arXiv/bioRxiv/medRxiv
  "arxiv_id": "arXiv:2508.01234",              // optional
  "pmid": "12345678",                          // optional
  "pmcid": "PMC1234567",                       // optional
  "source": "crossref|epmc|openalex|pubmed|arxiv|biorxiv|medrxiv|dblp",
  "ingested_at": "UTC ISO8601",
  "source_url": "string"                       // if available; no scraping
}
```

### 3.2 Weekly artifact

* File: `discovery_results_{YYYY-WW}.ndjson`
* Location: repo artifact + object storage (configurable).
* Acceptance: ≥50 unique DOIs; duplicates by DOI ≤1%; **preprints flagged**.

### 3.3 Canonicalization rules

* **DOI:** trim, lowercase, remove `https://doi.org/` prefix; store raw & canonical.
* **Dates:** use source “published-online” else “published-print” else “created”.
* **Dedup Key Order:** `doi` → `arxiv_id` → `pmid`/`pmcid`.
* **Preprint→Published:** if both exist, **keep both** but mark `is_preprint` for preprint; downstream can map progression.

---

## 4) Scheduling & Throughput

* **Cron:** weekly Tuesday 09:00 Europe/Rome (adjustable) for the **last 60 days**.
* **On-demand replays:** same window; idempotent via (source, cursor, window) checkpointing.
* **Rate limits:** obey each API; exponential backoff on 429/5xx; jitter.

---

## 5) Source Queries (templates; implement as clients)

> Implement clients with **cursor/deep-paging** where available. All clients must expose:
> `fetch(window_start, window_end) -> Iterable[RawItems]` + structured metrics.

**Crossref**

* Filter: `type=journal-article`, `from-pub-date`, `until-pub-date`
* Fields: DOI, title, container-title, issued/published, subject
* Paging: `cursor=*` until empty
* Notes: set `User-Agent` + `mailto` for polite pool

**Europe PMC**

* Query: `HAS_DOI:Y` AND `(PUB_TYPE:"Journal Article" OR PUB_TYPE:preprint)` AND neuro terms
* Date: `FIRST_PDATE:[start TO end]`
* Paging: `cursorMark=*`
* Keep `PMID`, `PMCID`, `DOI`, `isOpenAccess`, `pubType`

**OpenAlex**

* Filter: `has_doi:true`, `publication_date:start:end`, `concepts.id in {neuro IDs}`
* Use for cross-field ML/neuro papers; gather venue + concept IDs

**PubMed (E-utilities)**

* ESearch with neuro query + date range → PMIDs
* ESummary/ELink to pull DOI where present (enrichment/verification)

**Preprints**

* **arXiv**: categories `cs.NE`, `q-bio.NC`, `q-bio.NM`, `eess.IV`, `stat.ML`; sort by submittedDate; rate 1 req/3s
* **bioRxiv/medRxiv**: date-ranged JSON; includes `doi`; page by cursor

**DBLP**

* Venue/topic search for NeurIPS/ICLR/ICML/AISTATS/etc.; enrich missing DOIs via Crossref/OpenAlex

---

## 6) Taxonomy (defaults; editable)

### 6.1 Venue allowlist (starter)

* **Neuroscience:** *Nature Neuroscience, Neuron, eLife, PNAS, J Neurosci, NeuroImage, Cerebral Cortex, Brain, Nat Communications, Nat Human Behaviour, Nat Machine Intelligence (brain-adjacent), Sci Transl Med, PLoS Biology, PLoS Comp Bio, eNeuro*
* **Clinical/Systems:** *Brain Communications, Annals of Neurology, Neurology, Neuropsychologia*
* **AI/ML with neuro relevance:** *NeurIPS, ICML, ICLR, AISTATS, PMLR volumes with neuro/BCI, TMLR, Nature Machine Intelligence*

### 6.2 Concept set (OpenAlex starter IDs—fill during implementation)

* *Neuroscience*, *Computational neuroscience*, *Brain–computer interface*, *Cognitive neuroscience*, *Neural decoding*, *EEG/MEG/fMRI*, *Neuromodulation*, *Reinforcement learning (when brain-applied)*

> Architect: during first run, instruct a coding agent to resolve concrete concept IDs and pin them into `config/concepts.json`.

---

## 7) IPFS Integration (downstream handshake)

* Content retrieval is **already implemented** against a copyright-compliant DB, addressable via IPFS.
* Smoke-test step (optional but recommended in CI): for **5 random DOIs** from the weekly artifact:

  1. **Normalize DOI** → path element (lowercase; replace unsafe path chars).
  2. Run: `ipfs pin add /ipns/libstc.cc/dois` (module handles lookup by DOI).
  3. Assert non-error return + content CID logged.
* All IPFS operations are **read/pin** only; no distribution here.

> If path encoding is required, define a helper: `encode_doi_for_path(doi)`: lowercase, URL-encode `/` and spaces. Document exact rule in `docs/ipfs.md`.

---

## 8) Repos, Layout & Components (no code, just contracts)

```
/apps
  /discovery-runner        # CLI entry; wires jobs, windowing, outputs
/packages
  /clients                 # Crossref/EPMC/OpenAlex/PubMed/arXiv/medRxiv/DBLP
  /normalizer              # field mapping, date selection, boolean is_preprint
  /deduper                 # key strategy + stable sort by peer-reviewed > preprint
  /emitter                 # writes NDJSON + summary metrics.json
  /ipfs-smoke              # optional check: random pin attempts
/config
  sources.yaml             # endpoints, rate limits, headers
  venues.yaml              # allowlist/denylist
  concepts.json            # OpenAlex concept IDs
  schedule.yaml            # cron, window (days)
  thresholds.yaml          # ≥50/week target; alarms
/docs
  /runbook.md              # replay, disable, roll back
  /ipfs.md                 # DOI→IPFS handshake notes
  /observability.md        # metrics, alerts
```

---

## 9) Orchestration Plan (phased; with acceptance criteria)

### M0 — Scaffold (1–2 PRs)

* **Done when:** repo skeleton, configs, CI (lint, type check), empty runners with mocks.

### M1 — Ingest & Normalize

* Implement **Crossref** + **Europe PMC** clients (with paging).
* Normalizer maps to output schema; `is_preprint` set.
* **Done when:** 2 sources produce ≥50 items combined in the last 60-day window in staging.

### M2 — Dedupe & Enrichment

* Add **OpenAlex** + **PubMed** (PMID→DOI enrichment).
* Implement deduper (doi→arxiv\_id→pmid/pmcid).
* **Done when:** duplicates by DOI ≤1%; item shows consistent `pub_date` & venue.

### M3 — Preprints & CS/ML sweep

* Add **arXiv** + **bioRxiv/medRxiv** + **DBLP**.
* Ensure preprints labeled; if published DOI exists in Crossref/OpenAlex, both entries persist but marked.
* **Done when:** preprints correctly flagged; counts per source logged.

### M4 — Emit, Smoke IPFS, Observe

* Emit weekly NDJSON artifact + metrics.
* Optional smoke IPFS pin for 5 sample DOIs.
* Alerts on: pipeline failure; <50 DOIs; any source 5xx spikes.
* **Done when:** one end-to-end weekly run passes with artifacts uploaded.

---

## 10) Observability & SLOs

* **Metrics (per run & per source):** items fetched, deduped count, RPS, 2xx/4xx/5xx, retries, final DOI count, % preprints.
* **SLO:** 99% weekly success; median runtime < 10 min; final count ≥50.
* **Alerts:**

  * CRIT: final count <50
  * WARN: any source unreachable >15 min
  * WARN: duplicates by DOI >1%

---

## 11) Safety, Compliance, and Respectful Use

* Use **official APIs/feeds** only; respect ToS, rate limits, attribution.
* No scraping paywalled content.
* Mark **preprints** explicitly (`is_preprint=true`).
* Keep provenance (`source`, `source_url`) in each record.

---

## 12) Config & Secrets (env vars)

```
DISCOVERY_WINDOW_DAYS=60
SCHEDULE_CRON="0 9 * * TUE"           # Europe/Rome timezone
MAX_RPS_CROSSREF=10
MAX_RPS_EPMC=5
ARXIV_REQ_INTERVAL_MS=3500
HTTP_TIMEOUT_MS=20000
RETRY_BACKOFF_MS=500..8000 (exp+jitter)
USER_AGENT="e-brain-bot/1.0 (+contact@email)"
CONTACT_MAILTO="contact@email"

# Optional keys if used:
OPENALEX_EMAIL=...
NCBI_API_KEY=...        # (improves E-utilities throughput)
SEMANTIC_SCHOLAR_KEY=... (if used)
```

---

## 13) Testing Strategy

* **Unit:** clients (pagination, filtering), normalizer, deduper, emitter.
* **Contract tests:** real API smoke with tiny window (e.g., 3 days).
* **Replay tests:** run same window twice → identical NDJSON (idempotent).
* **Property tests:** DOI canonicalization; date fallback logic.
* **IPFS smoke:** 5 random DOIs → `ipfs pin add /ipns/libstc.cc/dois` returns success.

---

## 14) Runbook (ops)

* **Replay:** rerun with same `window_start/end` → outputs overwrite; version with run id.
* **Disable a source:** toggle in `sources.yaml` and commit; CI redeploy.
* **Backfill:** temporarily set `DISCOVERY_WINDOW_DAYS=90` (cost warning), observe counts.
* **DLQ:** on persistent 5xx or schema errors, park raw items for inspection, do not block run.

---

## 15) Risks & Mitigations (top 3)

1. **API schema drift / outages** → Versioned clients, feature flags per source, fast fallbacks (continue without one source).
2. **Underflow (<50 DOIs)** → Expand venues/concepts automatically on shortfall; widen date window up to 90 days with warning.
3. **Version duplication (preprint vs. journal)** → Explicit `is_preprint`; store both; downstream logic can prefer peer-review.

---

## 16) Git & PR Protocol (for all coding agents)

* **Branching:** `feat/{component}-{short}`; **Conventional Commits**.
* **PR Checklist:** unit tests, contract test (tiny window), docs updated, metrics added, dry-run artifact attached.
* **CI gates:** lint, typecheck, tests, minimal live smoke for Crossref+EPMC (3-day window).
* **One PR per atomic step** (easier review/rollback).
* Always link the PR to a tracked task (see §17 prompts).

---

## 17) Prompts the Architect Sends to Coding Agents (ready-to-use)

### 17.1 Client implementation (example: Crossref)

> **Role:** Senior backend engineer
> **Goal:** Implement `packages/clients/crossref` with deep-paging (cursor), filters `type=journal-article`, date window, and polite headers.
> **Deliver:**
>
> 1. `fetch(window_start, window_end) -> Iterable[RawItems]`
> 2. Unit tests for paging + filters
> 3. Contract test against a 3-day window
> 4. Metrics: items, pages, RPS, retries
> 5. Update `sources.yaml` with rate limits
>    **Acceptance:** Produces ≥200 items for a typical 3-day span (non-holiday), correct fields present (DOI, title, venue, issued/published).
>    **Output:** Open a PR `feat/clients-crossref` with artifacts attached.

### 17.2 Normalizer

> Map Crossref/EPMC/OpenAlex items to the output schema; date selection rule (online→print→created); DOI canonicalization; `is_preprint` inference. Tests for edge cases.

### 17.3 Deduper

> Implement DOI→arXiv→PMID/PMCID keying; stable sort preferring peer-reviewed. Property tests for collision scenarios.

### 17.4 Emitter

> Write `discovery_results_{YYYY-WW}.ndjson` + `metrics.json`; include per-source counts and final deduped total.

### 17.5 Preprints suite

> Add arXiv + bioRxiv/medRxiv clients with rate limits. Ensure `is_preprint=true` and `arxiv_id` capture.

### 17.6 OpenAlex & PubMed enrichment

> Add clients that enrich venue/date/DOI where missing; merge by identifiers; unit + contract tests.

### 17.7 IPFS smoke

> Implement `/packages/ipfs-smoke`: randomly select 5 DOIs from emitted NDJSON; call `ipfs pin add /ipns/libstc.cc/dois`; log verdicts. Wire into CI post-artifact (non-blocking).

### 17.8 Observability

> Add metrics collector and simple dashboard JSON; set alerts: <50 DOIs (CRIT); source down (WARN).

---

## 18) Default Queries (drop-in, to be parameterized)

* **Window:** `[today-60d, today]` (absolute dates in UTC; logs must print exact dates).
* **Crossref:** `type=journal-article & from-pub-date & until-pub-date & cursor=*`
* **EPMC:** `HAS_DOI:Y AND (PUB_TYPE:"Journal Article" OR PUB_TYPE:preprint) AND (neuroscience OR "computational neuroscience" OR brain OR EEG OR MEG OR fMRI OR BCI OR hippocampus OR cortex) AND FIRST_PDATE:[start TO end] & cursorMark=*`
* **OpenAlex:** `has_doi:true & publication_date:start:end & concepts.id in (...)`
* **arXiv:** `cat:cs.NE OR q-bio.NC OR q-bio.NM OR eess.IV OR stat.ML` sorted by `submittedDate`
* **bioRxiv/medRxiv:** date-ranged details endpoints with cursor paging
* **PubMed:** ESearch+ESummary for neuro query within date range

> All queries live in `/config/sources.yaml` with clear comments and knobs.

---

## 19) Quality Gates (the pipeline fails if…)

* Final deduped count **<50** DOIs (hard gate; suggest widen venues or window).
* Any record **without DOI**.
* **Preprint records** missing `is_preprint:true`.
* Emitted file invalid NDJSON (schema validation fails).

---

## 20) Next Actions (what happens now)

1. **Architect** opens tasks: Crossref client, EPMC client, normalizer, deduper, emitter, minimal runner (M0–M1).
2. **Coding agents** implement per §17 prompts → one PR each with tests and artifacts.
3. **Architect** merges once CI passes and dry-run yields ≥50 items over 60-day window in staging.
4. Add preprints + OpenAlex + PubMed enrichment (M2–M3).
5. Wire IPFS smoke + alerts (M4).
6. Turn on weekly cron.

---

## 21) Explicit Defaults (change only if needed)

* **Discovery window:** 60 days
* **Weekly cron:** Tue 09:00 Europe/Rome
* **Sources on by default:** Crossref, EPMC, OpenAlex
* **Preprints:** included, flagged
* **Output path:** `/artifacts/discovery_results_{YYYY-WW}.ndjson`
* **Threshold:** ≥50 DOIs/week
* **DOI normalization:** lowercase, strip `doi.org/` prefix

---

## 22) Documentation To Keep Updated (auto-nudge)

After every merged PR that **changes behavior or config**, the Architect must ensure updates to:

* `/docs/runbook.md` (replay/disable/rollback notes)
* `/docs/observability.md` (new metrics or alerts)
* `/config/*.yaml|json` (concept IDs, venues, rate limits)
* `/docs/ipfs.md` (any change in DOI→IPFS handshake)

Set a CI **post-merge reminder** that comments on the PR if docs/config diffs are missing.

---

### Appendix A: Minimal “Smoke” Prompts (for the Architect console)

**Kick off a 7-day tiny window (smoke):**

> Run `discovery-runner --from 2025-08-30 --to 2025-09-06 --emit ./artifacts/smoke.ndjson --sources crossref,epmc --dry-run`

**If final count <50 in full window:**

> Re-run with `venues.yaml` expanded; if still <50, widen window to 90 days and open a task “broaden concepts” for OpenAlex.

**IPFS sample pin:**

> For 5 sample DOIs from `smoke.ndjson`, call `ipfs pin add /ipns/libstc.cc/dois` and log CIDs.

---

**End of ARCHITECT.md**
