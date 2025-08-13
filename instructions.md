*** Begin Patch
*** Update File: instructions.md
@@
 ## CONTEXT
 We are building a **DOGEai-style pipeline** adapted to **neuroscience-themed co
ntent**.
 The system will:
-1. Pull data from X using the official API (https://docs.x.com/x-api/introducti
on), specifically:
-   - Following and monitoring the accounts followed by `@smol_ai`.
-   - Optionally ingesting selected neuroscience-related accounts and RSS/blog f
eeds.
-2. Process and embed the ingested content using **OpenAI’s `text-embedding-smal
l`** model.
-3. Store embeddings in a lightweight vector DB (e.g., SQLite + pgvector, or loc
al FAISS for MVP).
+1. Pull data from X using the official API (see X developer docs), specifically
:
+   - Monitoring the accounts listed in `accounts-to-follow.md`.
+   - Optionally ingesting selected neuroscience-related accounts and RSS/blog f
eeds.
+2. Process and embed the ingested content using **OpenAI’s `text-embedding-3-sm
all`** model.
+3. Store embeddings in **PostgreSQL with `pgvector`** for semantic retrieval.
 4. Periodically generate X posts covering:
    - Common neuroscience facts.
    - Niche arguments.
    - Recent findings.
    - Core neuroscientific theories and concepts.
    - Computational neuroscience topics.
 5. Moderate output to avoid unsafe or misleading content.
 6. Publish automatically to X using the pipeline defined in `publisher.py`.

---
## TROUBLESHOOTING: X Ingestion

- Symptom: repeated `x_api_error` lines while some `raw_items_inserted` appear.
- Likely causes:
  - 401/403 due to invalid Bearer token or insufficient API tier (free tier often blocks v2 timeline/user lookups).
  - 429 rate limiting; too many requests without backoff.
  - Host mismatch; try `X_API_BASE=api.twitter.com` vs `api.x.com` depending on your app’s availability.
- What we log now: status, host, path, and a short response body to pinpoint the failure.
- Quick checks:
  - Ensure `.env` contains `X_BEARER_TOKEN` (App-only) and matches the project’s access level.
  - Optionally set `X_API_BASE=api.twitter.com` if you see DNS/404 issues against `api.x.com`.
  - Run: `python -m e_brain.cli ingest-x --max 1` and inspect the JSON logs for `status` and `body`.
- Note: A `KeyboardInterrupt` stack in `db.upsert_source_x` just means you pressed Ctrl-C while a DB call was active; it’s not a deadlock.

 ## REQUIREMENTS

 ### Functional
 - **Curation Layer**:
   - Fetch recent posts from target X accounts.
   - Optionally ingest from specified RSS/blog feeds.
   - Store raw text, timestamp, and source.

 - **Embedding Layer**:
-  - Use `text-embedding-small` to convert curated items into embeddings.
-  - Store embeddings in a retrievable format for semantic search.
+  - Use `text-embedding-3-small` to convert curated items into embeddings.
+  - Store embeddings in PostgreSQL + `pgvector` for semantic search.

 - **Generation Layer**:
   - Retrieve relevant curated content based on themes or queries.
   - Use GPT models to synthesize high-quality, audience-ready tweets.
-  - Inject variety: mix common knowledge, deep dives, and fresh news.
+  - Inject variety: mix common knowledge, deep dives, and fresh news.
+  - Support short posts by default, with occasional long posts.

 - **Moderation Layer**:
   - Check output length (<= 280 chars).
   - Blocklist unsafe terms.
   - Flag ambiguous or unverifiable claims.

 - **Publishing Layer**:
-  - Use FastAPI background tasks for scheduled publishing.
-  - Poll mentions/DMs for non-real-time replies.
+  - Use a scheduler (e.g., APScheduler or cron) for time-windowed publishing in
 US (ET) and EU (CET/CEST) timezones.
+  - No DMs; mentions polling optional and disabled by default due to free tier
constraints.
   - Support dry-run mode for testing.
+  - Support occasional long posts when permitted; otherwise thread-split as nee
ded.

 ---

## TECHNICAL CONSTRAINTS
 - All credentials loaded from `.env`.
-- All write actions to X must be authorized via a Bearer token in API requests.
+- All write actions to X must use OAuth user-context tokens (OAuth 2.0 or OAuth
 1.0a) with appropriate scopes.
 - Must respect X API rate limits and ToS.
 - DRY_RUN=true in development until explicitly disabled.
- Use structured logging with timestamps and context.
- Code should be modular and testable.

## X API Ingestion – Operational Notes
- API host: use `api.x.com` for v2 endpoints by default. Configurable via `X_API_BASE`.
- Endpoints used:
  - `GET /2/users/by/username/:username`
  - `GET /2/users/:id/tweets?tweet.fields=created_at,author_id,text`
- Auth: App-only Bearer token (`X_BEARER_TOKEN`) with Tweet read permissions.
- Logging: `x_api_error` now includes status, host, path, and a body snippet to aid debugging.
- Common failures and fixes:
  - 401/403: invalid or insufficient tier; regenerate token or upgrade access.
  - 404: invalid username or protected/suspended account.
  - 429: rate-limited; reduce `--max` or add backoff.
  - DNS/connectivity: override `X_API_BASE` if X changes domains.

 ---

 ## EXAMPLES

 ### Example Retrieval → Post Flow:
 1. Retrieve 5 recent items from target accounts.
-2. Embed with `text-embedding-small`.
+2. Embed with `text-embedding-3-small`.
 3. Query embeddings with: `"recent breakthrough in computational neuroscience"`
.
 4. Synthesize tweet:
 Your brain's 86 billion neurons aren't just connected — they're constantly rewi
 New computational models suggest this rewiring follows efficiency rules similar
 to AI neural nets. 🤯


 ---

 ## UPDATE PROTOCOL
 When direction changes:
 1. Append a **`CHANGELOG`** entry in this file.
 2. Codex must **re-read the entire prompt** before next execution.
 3. If new data sources, models, or constraints are added, update the relevant s
ection in **CONTEXT** or **REQUIREMENTS**.
 4. Maintain backward compatibility unless explicitly told otherwise.

 ---

 ## CHANGELOG
 - **v1.0** — Initial specification integrating X API usage, blog curation, embe
ddings, and neuroscience focus.
+- **v1.1** — Switch to `text-embedding-3-small`; standardize on PostgreSQL + `p
gvector`; replace curation source with `accounts-to-follow.md`; add scheduled po
sting in US/EU windows; disable DMs and mentions by default on free tier; add su
pport for occasional long posts.
 ---
*** End Patch
