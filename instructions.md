

**Role**: You are `Codex`, a precise coding agent. Build a minimal, end-to-end terminal pipeline that ingests neuroscience/AI news from RSS, extracts articles, clusters near-duplicates, computes embeddings with OpenAI’s **text-embedding-3-small**, summarizes clusters with citations in a watchdog tone, and writes results to a timestamped output folder. No web UI. Tests + runbook included. Keep it light, dependency-lean, and resilient.

**Requirements & Acceptance Criteria**

* Python 3.11+. Single package `pipeline/` with CLI via `python -m pipeline`.
* Create:

  ```
  README.md
  pyproject.toml
  pipeline/__init__.py
  pipeline/__main__.py              # Typer CLI: fetch, extract, cluster, summarize, publish, all
  pipeline/config.py
  pipeline/logging.py
  pipeline/io.py
  pipeline/ingest.py                # RSS fetch with feedparser; ETag/Last-Modified caching
  pipeline/extract.py               # Canonical URL + trafilatura extraction; robots aware
  pipeline/normalize.py             # Unified schema
  pipeline/cluster.py               # URL canon + SimHash (text) + optional embed centroid
  pipeline/embed.py                 # OpenAI embeddings (text-embedding-3-small); cache by content hash
  pipeline/summarize.py             # map→reduce summaries with citations; tone applied
  pipeline/rank.py                  # freshness + source weight + cluster size
  config/sources.yml                # curated RSS list + weights
  config/tone.md                    # tone rules below
  .env.example
  tests/test_cluster.py
  tests/test_url_canon.py
  tests/test_embed_shape.py
  ```
* Storage:

  * Local SQLite DB at `./state/pipeline.sqlite` (articles, clusters, embeddings).
  * Filesystem artifacts under `./pipeline_runs/<ISO8601UTC>/`.
* Performance & safety:

  * Respect robots/TOS; throttle requests (default 2 req/s host); timeouts; retries with jitter/backoff.
  * Use HTTP caching (ETag/Last-Modified written to SQLite).
  * Idempotent: re-running `all` should not duplicate work or re-embed identical content.

**CLI spec**

* `python -m pipeline all --out ./pipeline_runs --since 2025-09-01T00:00:00Z`
* Flags: `--out`, `--since`, `--max-items`, `--dry-run`, `--log-level`, `--parallel N`
* Commands: `fetch`, `extract`, `cluster`, `summarize`, `publish`, `all`

**Schemas (JSON-serializable)**

* `ArticleRaw`: `{source_id, feed_url, entry_id, link, title, summary, published_at, fetched_at, etag, last_modified}`
* `Article`: `{article_id, canonical_url, title, byline, published_at, source_id, is_preprint, text, lang, tags[], extraction_quality, content_hash}`
* `Cluster`: `{cluster_id, article_ids[], method: "simhash+embed", centroid_embed: [..], representative_article_id}`
* `Summary`: `{cluster_id, bullets[], delta, citations: [{title, outlet, url, date}], labeled_preprint: bool, created_at}`

**Tone (put this verbatim into `config/tone.md`)**

* Persona: **Evidence-first watchdog**, slightly calmer than @dogeai\_gov. Direct, receipts-led, no hype.
* Rules:

  1. Contrast claims vs. rigorous practice.
  2. Cite primary sources; label preprints explicitly.
  3. Use absolute dates.
  4. Short, firm bullets; no emojis/hashtags in lead.
  5. Bottom line: what changed and why it matters.
* Summary form (map→reduce):

  * Map (per article): 2 bullets: claim/result + key method/limit; add citation.
  * Reduce (per cluster): 3–5 bullets “what changed,” note disagreements, label preprints; end with “Bottom line: …”.

**Curated RSS defaults (`config/sources.yml`)**
Include at least these (comment each with a `weight` 1–3):

* arXiv: cs.NE, cs.LG, q-bio.NC (RSS query feeds)
* bioRxiv: Neuroscience
* Nature Neuroscience (RSS)
* eLife Neuroscience (RSS)
* PNAS Neuroscience (RSS)
* NIH Director’s Blog
* MIT Technology Review (AI tag RSS)
  (Implement a `weight` field and store it in `source_id → weight` for ranking.)

**Implementation details**

* Use: `feedparser`, `trafilatura`, `typer`, `requests`, `sqlite3` (std lib), `tenacity` for retries, `python-dotenv`.
* URL canonicalization: strip tracking params; use `url-normalize`; prefer `og:url` if available via trafilatura metadata.
* SimHash: implement lightweight 64-bit simhash on shingles of normalized text; threshold adjustable (default Hamming ≤ 8).
* Embeddings: OpenAI `text-embedding-3-small`; up to 4000 tokens chunk; average-pool to 1 vector/article. Cache by `content_hash`.
* Ranking rule: `score = 0.5·freshness_decay + 0.3·source_weight + 0.2·cluster_size`.
* Publishing:

  * `summaries.md` (ranked, human-readable, cluster headers, bullets, citations as list)
  * `clusters.json` (full objects)
  * `run_report.json` (counts, durations, failures, rate-limit stats)
  * `logs/run.log`

**Developer Experience**

* `README.md` with quickstart: `uv venv` or `python -m venv`, install, `.env` setup, run examples.
* Tests runnable via `pytest -q`; keep them minimal but real.
* Add make-like tasks in `pyproject.toml` using `tool.pdm.scripts` or simple `Makefile` if easier.

**Non-goals for MVP**

* No web UI, no background scheduler, no vector DB beyond SQLite.
* No advanced rerankers; no LLM longform posts yet.

**Deliverables**

1. Full file tree and contents.
2. Instructions in README to run `python -m pipeline all`.
3. First run should produce a non-empty `summaries.md` with at least 3 clusters (given live feeds).
4. Clear TODOs at file tops for the next iteration (publishing to X, web UI).

Start now. When finished, print:

* A short summary of what was created,
* How to run it end-to-end,
* Example command,
* And any .env keys needed.

---


