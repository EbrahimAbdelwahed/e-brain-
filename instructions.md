## CONTEXT

We are building a DOGEai-style pipeline adapted to neuroscience-themed content.

The system will:
1. Pull data from X using the official API (see X developer docs), specifically:
   - Monitoring the accounts listed in `accounts-to-follow.md`.
   - Optionally ingesting selected neuroscience-related accounts and RSS/blog feeds.
2. Process and embed the ingested content using OpenAI’s `text-embedding-3-small` model.
3. Store embeddings in PostgreSQL with `pgvector` for semantic retrieval.
4. Periodically generate X posts covering:
   - Common neuroscience facts.
   - Niche arguments.
   - Recent findings.
   - Core neuroscientific theories and concepts.
   - Computational neuroscience topics.
5. Moderate output to avoid unsafe or misleading content.
6. Publish automatically to X using the pipeline defined in `publisher.py`.

---

## REQUIREMENTS

### Functional
- Curation Layer:
  - Fetch recent posts from target X accounts.
  - Ingest from specified RSS/blog feeds (academic + industry) focused on neuroscience/AI.
  - Clean and store full text + summary with tagging and source metadata.
  - Store raw text, timestamp, and source.

- Embedding Layer:
  - Use `text-embedding-3-small` to convert curated items into embeddings.
  - Store embeddings in PostgreSQL + `pgvector` for semantic search.

- Generation Layer:
  - Retrieve relevant curated content based on themes or queries.
  - Use GPT models to synthesize high-quality, audience-ready tweets.
  - Inject variety: mix common knowledge, deep dives, and fresh news.
  - Support short posts by default, with occasional long posts.

- Moderation Layer:
  - Check output length (<= 280 chars).
  - Blocklist unsafe terms.
  - Flag ambiguous or unverifiable claims.

- Publishing Layer:
  - Use a scheduler (e.g., APScheduler or cron) for time-windowed publishing in US (ET) and EU (CET/CEST) timezones.
  - No DMs; mentions polling optional and disabled by default due to free tier constraints.
  - Support dry-run mode for testing.
  - Support occasional long posts when permitted; otherwise thread-split as needed.

---

## TECHNICAL CONSTRAINTS
- All credentials loaded from `.env`.
- All write actions to X must use OAuth user-context tokens (OAuth 2.0 or OAuth 1.0a) with appropriate scopes.
- Must respect X API rate limits and ToS.
- DRY_RUN=true in development until explicitly disabled.
- Use structured logging with timestamps and context.
- Code should be modular and testable.

---

## X API Ingestion – Operational Notes
- API host: use `api.x.com` for v2 endpoints by default. Configurable via `X_API_BASE`.
- Endpoints used:
  - `GET /2/users/by/username/:username`
  - `GET /2/users/:id/tweets?tweet.fields=created_at,author_id,text`
- Auth: App-only Bearer token (`X_BEARER_TOKEN`) with Tweet read permissions.
- Logging: `x_api_error` includes status, host, path, and a body snippet to aid debugging.
- Common failures and fixes:
  - 401/403: invalid or insufficient tier; regenerate token or upgrade access.
  - 404: invalid username or protected/suspended account.
  - 429: rate-limited; reduce `--max` or add backoff.
  - DNS/connectivity: override `X_API_BASE` if X changes domains.

Troubleshooting
- Symptom: repeated `x_api_error` with intermittent `raw_items_inserted`.
- Quick checks:
  - Ensure `.env` contains `X_BEARER_TOKEN` and matches app permissions.
  - Try `X_API_BASE=api.twitter.com` if host issues persist.
  - Run: `python -m e_brain.cli ingest-x --max 1` and inspect JSON logs.
- Note: A `KeyboardInterrupt` stack in `db.upsert_source_x` means Ctrl-C during a DB call; not a deadlock.

---

## RSS/Blog Ingestion – Design

- Purpose: Curate and aggregate high-signal neuroscience/brain sciences/computational neuroscience/AI content.
- Sources: Reputable blogs, journals, and RSS feeds (academic + industry).
- Behavior:
  - Periodically fetch feeds; clean HTML to text; store full text in `raw_items.text` and summary/title/url/tags in `raw_items.meta`.
  - Tag items using feed-provided categories and light keyword filters.
  - Maintain `sources.meta.last_fetched_at` for pacing; scheduling is left to caller (CLI/cron).
- Schema:
  - `raw_items` includes: `source_type ('x'|'rss')`, `source_ref`, `source_id`, `author`, `text`, `meta JSONB`, `created_at`.
  - `raw_items.meta` stores `{ "title", "url", "summary", "tags" }`.
  - `sources` table stores `type`, `handle|url`, and `meta JSONB` (e.g., `{ "title", "last_fetched_at" }`).
- Configurability (CLI):
  - `--feeds-file`: optional newline list to override defaults.
  - `--max`: cap entries per feed (default 20).
  - `--interval-mins`: stored in source meta to guide schedulers.
  - `--filter`: regex to include items (default targets neuro/brain/AI terms).
- Starter feeds:
  - https://www.nature.com/neuro.rss
  - https://www.frontiersin.org/journals/neuroscience/rss
  - https://www.jneurosci.org/rss/current.xml
  - https://news.mit.edu/rss/topic/brain-and-cognitive-sciences
  - https://neuroscience.stanford.edu/news/rss.xml
  - https://neuromatch.io/feed.xml
  - https://www.cogneurosociety.org/feed/
  - https://export.arxiv.org/rss/cs.AI
  - https://distill.pub/rss.xml
  - https://deepmind.com/blog/feed/basic/

CLI usage
- Initialize/upgrade DB: `python -m e_brain.cli init-db`
- Ingest RSS: `python -m e_brain.cli ingest-rss --max 20`
- Custom feeds: `python -m e_brain.cli ingest-rss --feeds-file myfeeds.txt --filter "(neuro|brain|AI)"`

Troubleshooting
- If inserts fail with meta column errors, re-run `init-db` to add `raw_items.meta`.
- For full-text extraction we use BeautifulSoup; some pages may result in abbreviated text.

---

## EXAMPLES

Example Retrieval → Post Flow:
1. Retrieve 5 recent items from target accounts.
2. Embed with `text-embedding-3-small`.
3. Query embeddings with: "recent breakthrough in computational neuroscience".
4. Synthesize tweet:
   Your brain's 86 billion neurons aren't just connected — they're constantly rewiring.
   New computational models suggest this rewiring follows efficiency rules similar to AI neural nets. 🤯

---

## UPDATE PROTOCOL
When direction changes:
1. Append a `CHANGELOG` entry in this file.
2. Codex must re-read the entire prompt before next execution.
3. If new data sources, models, or constraints are added, update the relevant section in CONTEXT or REQUIREMENTS.
4. Maintain backward compatibility unless explicitly told otherwise.

---

## CHANGELOG
- v1.0 — Initial specification integrating X API usage, blog curation, embeddings, and neuroscience focus.
- v1.1 — Switch to `text-embedding-3-small`; standardize on PostgreSQL + `pgvector`; replace curation source with `accounts-to-follow.md`; add scheduled posting in US/EU windows; disable DMs and mentions by default on free tier; add support for occasional long posts.
- v1.2 — Add RSS/blog ingestion module with starter feeds; store full text + summary and tags in `raw_items.meta`; new CLI `ingest-rss`; DB `raw_items.meta` column and source meta updates.

