
---

# ARCHITECT.md — NeuroScope / AI News Pipeline (MVP: Terminal-first)

**Status:** Source of truth (authoritative)
**Date:** 2025-09-03 (Europe/Rome)
**Owner:** Architect/Strategist (this file); implementation by a separate coding agent/model.

---

## 0) Identity & Inspiration

- Working name: NeuroScope (brand umbrella; future expansion to Bio/ML possible).
- Inspiration: AI News by smol_ai; @dogeai_gov tone (receipts-first, calmer).
- Primary channel (MVP): Terminal-only outputs. X publishing planned post-MVP once stable.

---

## 1) Mission & Non-Goals

- Mission: Deliver a low-cost, maintainable, reliable terminal pipeline that:
  1) Ingests neuro/AI items (RSS + explicitly allowed pages),
  2) Normalizes & canonicalizes,
  3) Clusters near-duplicates,
  4) Summarizes at the cluster level with clear citations & qualifiers,
  5) Ranks by freshness/impact,
  6) Publishes watchdog-style outputs formatted as X threads into Markdown for review.
- Non-Goals (MVP):
  - Social publishing (X) during MVP; enable after thorough testing.
  - Broad web crawling beyond feeds & explicitly allowed pages.
  - Heavy MLOps; complex orchestration; custom UI.

---

## 2) Operating Principles (Normative)

- MVP-first, end-to-end: a thin, complete loop over partial sophistication.
- RSS-first; fetch article pages only when robots.txt permits; polite throttling (RFC 9309).
- Cluster-centric output: one story → one cluster; dedupe at cluster level.
- Citations-first: clear links, outlet names; label preprints; avoid medical advice.
- Lean ops: idempotent stages, retries, minimal state.
- Cost control: cache LLM outputs; batch embeddings; respect API quotas.
- Clarity > cleverness: explicit inputs/outputs; acceptance tests.

---

## 3) Finalized Decisions (MVP Defaults)

1) Channel & Outputs
- Artifacts written to `./pipeline_runs/<ISO8601UTC>/`.
- Outputs shaped like X threads (lead + Sources) but saved as Markdown.

2) Execution cadence
- On-demand via CLI; external cron optional and out of scope.

3) Approval workflow
- Human reviews generated summaries; no automated social publishing.

4) Voice & style
- Persona: evidence-first watchdog; slightly calmer than @dogeai_gov.
- Tone rules kept in `config/tone.md` (see §14).

5) Source scope (start)
- RSS feeds from journals/societies, preprint servers, high-signal blogs (see `config/sources.yml`).

6) Crawling stance
- RSS + explicitly allowed pages; respect robots.txt; retry/backoff.

7) Storage/DB
- Neon Postgres with pgvector (primary). Optional SQLite only for local tests if required.

8) Orchestration
- Typer-based CLI (`python -m pipeline`): `fetch`, `extract`, `cluster`, `summarize`, `publish`, `all`.

9) Dedup/Clustering
- MinHash/LSH via `datasketch`; persist signature; start Jaccard ≈ 0.85 (tunable).

10) Embeddings
- OpenAI `text-embedding-3-small`; chunk ≤ 4000 tokens; average-pool; cache by `content_hash`.

11) LLM Access & cost
- Direct OpenAI usage via `.env`; batch and cache; respect rate limits.

12) Ranking (starter rule)
- score = 0.5·freshness_decay + 0.3·source_weight + 0.2·cluster_size
- Boosts: prereg/code/replication/policy; Penalize PR-only.

13) Observability
- Langfuse traces hooks; local logs; `run_report.json` per run.

---

## 4) Architecture (Conceptual & Binding)

- Stages: Ingest → Extract → Normalize/Canonicalize → Cluster/Dedupe → Embed → Summarize (map-reduce) → Rank → Publish (files) → Observe.
- Pattern: Each stage is an idempotent CLI subcommand reading/writing DB and files; re-runs should not duplicate work.
- Reliability: Retries with exponential backoff + jitter; bounded attempts; surface failures in report.
- Determinism: Canonicalization, clustering, summarization are pure given inputs + versioned prompts; cache keys include versions.
- Local runtime: Python 3.11+, Typer CLI; tests via pytest.

---

## 5) Package & CLI (MVP)

- Single Python package `pipeline/` with Typer CLI commands:
  - `fetch`, `extract`, `cluster`, `summarize`, `publish`, `all`.
- Flags: `--out`, `--since`, `--max-items`, `--dry-run`, `--log-level`, `--parallel N`.

---

## 6) Data Model (Relational, Minimal)

### articles
- id uuid (PK)
- url_canonical text UNIQUE (normalized; trackers stripped)
- source text
- title text
- byline text NULL
- published_at timestamptz
- ingested_at timestamptz DEFAULT now()
- text text (cleaned main content)
- raw_html text NULL (optional snapshot)
- hash_sig text (MinHash signature)
- embedding vector (pgvector)
- cluster_id uuid NULL (FK → clusters)
- metadata_json jsonb (e.g., {is_preprint, prereg_id, code_url, endpoints, sample_size, species, brain_area, modality, method})

### clusters
- cluster_id uuid (PK)
- first_seen timestamptz
- last_seen timestamptz
- size int
- representative_article_id uuid (FK)
- topic_tags text[] (controlled vocabulary; see §20 Ontology)

### summaries
- cluster_id uuid (PK, FK)
- tl_dr text (lead, ~280 chars target; threadable later)
- bullets_json jsonb (structured bullets array)
- citations_json jsonb ([{title, outlet, url, date}])
- score float
- created_at timestamptz DEFAULT now()
- published_at timestamptz NULL
- version_hash text (hash of prompt+guardrails+inputs)

Indexes
- articles(url_canonical) unique btree
- articles USING hnsw (embedding vector_cosine_ops) or IVFFlat when mature

---

## 7) Execution Contracts (CLI I/O)

- Commands read prior stage outputs and write normalized artifacts.
- Artifacts include `schema_version`, timestamps, and idempotency keys where relevant.
- Retries with jittered backoff for network I/O.

---

## 8) Ingestion & Extraction (Deterministic)

- Feed polling: CLI using feedparser for robust RSS/Atom parsing.
- Robots & throttling: Respect robots; per-domain concurrency = 1; dynamic backoff on 429/503 (RFC 9309).
- Extraction: Trafilatura for main text & metadata; optionally store raw HTML snapshot for reproducibility.
- Canonicalization: Resolve redirects, strip trackers (utm_*, fbclid, etc.), normalize scheme/host/path; stable url_canonical before DB write.

---

## 9) Clustering & Dedupe (Near-Duplicate)

- Technique: MinHash + LSH (datasketch).
- Preprocessing: Lowercase, strip boilerplate, Unicode normalize, tokenize to 5-gram shingles.
- Signature: MinHash (num_perm=128 default).
- Threshold: start at Jaccard ~0.85; tune from false-merge/false-split metrics.
- Cluster maintenance: update size, last_seen; choose representative_article_id by heuristic (longest clean body + strongest metadata).

---

## 10) Embeddings & Index

- Model: OpenAI text-embedding-3-small.
- Storage: pgvector in Neon; choose index:
  - HNSW for dynamic data & high recall.
  - IVFFlat for lower memory once dataset is mature.
- Build IVFFlat only after sufficient rows (per pgvector guidance).

---

## 11) Summarization (Map-Reduce) & Guardrails

- Map: Per article, extract facts: { is_preprint, sample_size, endpoints, prereg_id, code_url, effect_sizes (with CI), species, modality, method }.
- Reduce: Synthesize cluster-level lead + bullets with citations.
- LLM settings (determinism): temperature ≤ 0.2, top_p = 0.9; set seed if supported.
- Caching key: sha256(prompt_version + guardrails_version + sorted(article_ids) + joined_extracted_facts).
- Guardrails:
  - If is_preprint: include "preprint; may change post-review".
  - If sample_size < 50 or no power calc: phrase as exploratory; call for replication.
  - No medical advice; critique claims & methods, not people.

---

## 12) Ranking (Starter)

- Formula: 0.5·freshness_decay + 0.3·source_weight + 0.2·cluster_size
- Freshness: exponential decay; half-life ~18–36h for newsy items.
- Source weight: curated map; society journals > high-signal blogs > press releases.
- Boosts: prereg (+0.1), open code/data (+0.1), replication (+0.2), policy impact (+0.2).
- Penalty: PR-only (−0.2), missing methods (−0.1).

---

## 13) Publishing (Files; X-shaped Markdown)

- Artifacts:
  - summaries.md (ranked; per-cluster header; X-style lead; Sources section)
  - clusters.json (full objects)
  - run_report.json (counts, durations, failures, rate-limit stats)
  - logs/run.log
- Location: `./pipeline_runs/<ISO8601UTC>/`

---

## 14) Voice Pack (Prompts & Templates)

System (summarizer for X-shaped Markdown):
"You are NeuroScope, an evidence-first watchdog for neuroscience/AI news. Tone: direct, receipts-led, slightly calmer than @dogeai_gov. Contrast claims vs practice; cite primary sources; label preprints; use absolute dates; short, firm bullets; end with 'Bottom line: ...'. Prepare output shaped like an X thread lead plus a separate 'Sources' section."

Lead scaffold:
- Problem: {core claim/flaw}
- Contrast: {rigorous/transparent practice}
- Receipts: {2–3 numbers; note preprint/peer-review}
- Bottom line: {what changed + why it matters}
- Call to action: {read/replicate/wait for peer review/audit the data}

---

## 15) Observability, Analytics, Cost

- Traces: Langfuse per stage; attach cluster_id, token & latency metrics.
- Logs & reports: local log file and run_report.json per run.
- Cost controls: summarize after clustering; cache aggressively; batch embeddings.

---

## 16) Compliance & Safety

- Robots/ToS: RSS-first, obey robots.txt, gentle throttling (RFC 9309).
- Scientific caution: label preprints; avoid clinical advice; target claims/process, not individuals.
- Attribution: clear citations; link to originals; maintain normalized snapshots for reproducibility.
- X policies: plan compliance post-MVP; no automated posting during MVP.

---

## 19) Differentiators (Must Preserve)

1) Cluster-centric, cited summaries (no link dumps).
2) Delta-aware: “what changed since last time”.
3) Neuro-aware tags (brain area, modality, species, method).
4) Reproducibility: snapshots + versioned prompts.
5) Tone that rewards rigor, avoids ad hominem.

---

## 20) V1 Upgrades (Post-MVP)

- X Publisher: threads from approved clusters; sources reply; scheduling windows.
- Ontology: topic taxonomy; tag validation.
- Fact deltas: weekly number/date/outcome change detection.
- Feedback loop: clicks/completion → reweight ranking.
- Orchestration: consider lightweight job runner if needed; remain CLI-first unless demand.
- Search UI: hybrid BM25+vector over pgvector (optional later).

---

## 21) Collaboration Protocol (Architect ↔ Coding Model)

Each task should include:
1) Intent recap (1–2 lines).
2) Decision checklist (only blocking choices).
3) Plan (phases + acceptance + test notes).
4) Specs (I/O contracts, schema fields, env vars).
5) Risks & mitigations (top 3).
6) Next actions (owner, deadline).

Ambiguity not high-stakes → pick defaults, proceed, log in CHANGELOG.

---

## 22) Environment & Secrets (Names Only)

- OpenAI: `OPENAI_API_KEY`
- DB: `DATABASE_URL` (Neon Postgres with pgvector)
- Observability: (Langfuse keys when enabled later; optional during MVP)

---

## 23) KPIs (MVP)

- Output quality: number of clusters; correctness of citations; preprint labels.
- Reliability: E2E success; failures; p95 ingest→publish latency.
- Cost: average tokens/post; monthly spend vs cap.
- Review readiness: clarity and X-shape of Markdown output.

---

## 24) Change Management

Material changes must update this file and append CHANGELOG entry: (a) what changed, (b) why, (c) cost/ops impact, (d) next steps.

---

## 25) Current Defaults Snapshot (Quick Reference)

- Channel: Terminal-only (X-shaped Markdown outputs)
- Run: Typer CLI on-demand
- Ingest: RSS + allowed pages; robots-aware
- Extract: Trafilatura
- Dedupe: MinHash/LSH (datasketch)
- Embeddings: OpenAI text-embedding-3-small; pgvector on Neon
- Ranking: 0.5 freshness + 0.3 source + 0.2 cluster (+boosts/penalties)
- Publish: summaries.md (X-shaped), clusters.json, run_report.json, logs
- Observability: Langfuse traces; local logs
- Compliance: label preprints; no medical advice; respectful fetching

---

## 26) TODO / Open Items

- Finalize initial feed list (config/sources.yml)
- Define source_weight map
- Tune MinHash params & similarity threshold on labeled set
- Set freshness half-life & breaking policy
- Lock summarization prompt versions and guardrails

---

## 27) Changelog

- 2025-09-03: Consolidated to terminal-first MVP while planning X publishing post-MVP; Neon + pgvector; OpenAI embeddings; MinHash/LSH; Typer CLI; Langfuse hooks.
