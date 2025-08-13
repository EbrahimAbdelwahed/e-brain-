# Environment Setup (Neon + pgvector + X API)

This guide explains every environment variable the app uses, how to configure a Neon Postgres database with pgvector, and how to set up X (Twitter) API credentials for ingestion and posting.

## Overview
- Config source: a `.env` file at the repo root (example in `.env.example`).
- Loader behavior: the app loads `.env` if present and does NOT override already-set shell variables. Supports `KEY=VALUE`, ignores comments and blanks.
- Minimum versions: Python 3.11+, Postgres 14+ (Neon is fine), `pgvector` extension available in the database.

## Required Variables

Copy `.env.example` to `.env` and fill the following. Defaults shown in parentheses.

- `ENV`: deployment environment (`development`|`production`) — affects logging only. Default: `development`.
- `DRY_RUN`: if `true`, posting is simulated and nothing is sent to X. Default: `true`.

- `DATABASE_URL`: Postgres connection string. For Neon, use the provided URI and ensure SSL, for example:
  - `postgresql://<USER>:<PASSWORD>@<HOST>/<DBNAME>?sslmode=require`
  - You can use Neon’s pooled or direct connection string; both work with `psycopg`.

- `EMBEDDING_DIM`: vector length stored in DB (must match your embedding model). Default: `1536`.
  - Common values:
    - `text-embedding-3-small` → `1536` (default)
    - `text-embedding-3-large` → `3072`

- `OPENAI_API_KEY`: required. Used by embedding and generation.
- `EMBEDDING_MODEL`: OpenAI embedding model. Default: `text-embedding-3-small`.
- `CHAT_MODEL`: OpenAI chat model. Default: `gpt-4o-mini`.

- `X_BEARER_TOKEN`: required for read-only ingestion from X (App-only OAuth 2.0 Bearer).

- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`: user-context credentials for posting (OAuth 1.0a). The current publisher logs a placeholder; keep `DRY_RUN=true` unless you add OAuth signing.

- `POST_WINDOWS_US`: CSV of posting windows in US timezones, e.g. `09:00-12:00,17:00-19:00`.
- `POST_WINDOWS_EU`: CSV of posting windows in EU timezones, e.g. `08:00-11:00,18:00-20:00`.

Notes
- If you switch `EMBEDDING_MODEL`, update `EMBEDDING_DIM` to match before (re)creating the DB schema.
- The app reads `.env` automatically; you can also export variables in your shell instead.

## Neon + pgvector Setup

1) Create a Neon project and database
- In Neon, create a Project and a Database (and role/password). Copy the connection string.
- Prefer the `postgresql://...` URI and include `?sslmode=require`.

2) Set the connection
- Put your connection in `.env`:
  - `DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require`

3) Enable pgvector and create schema
- Run the app’s DB init, which ensures the `vector` extension and tables:
  - `python -m e_brain.cli init-db`
- What it does:
  - Executes `CREATE EXTENSION IF NOT EXISTS vector;`
  - Creates tables: `sources`, `raw_items`, `embeddings (embedding vector(EMBEDDING_DIM))`, `candidate_posts`.

4) Verify pgvector is active (optional)
- Connect with `psql` (or your client) and run:
  - `SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';`
  - You should see `vector` listed with a version.

5) Optional: add a vector index for faster search
- Preferred: HNSW. Use the built-in CLI:
  - `python -m e_brain.cli create-index --type hnsw`
- Fallback: IVFFlat, if HNSW is unavailable in your pgvector build:
  - `python -m e_brain.cli create-index --type ivfflat`
- The app will still work without an index; indexes mainly improve retrieval latency.

Troubleshooting
- “type "vector" does not exist”: ensure `init-db` ran successfully and your Neon project permits `CREATE EXTENSION vector`.
- Connection failures on Neon: make sure `sslmode=require` is present and credentials are correct.
- Wrong `EMBEDDING_DIM`: you’ll see casting errors or mismatched dimension issues. Drop/recreate `embeddings` (or re-run `init-db` after adjusting).

## X API Setup

Read-only ingestion (required for `ingest-x`)
- In the X (Twitter) developer portal, create a Project + App.
- Generate App-only Bearer token (OAuth 2.0) and put in `.env`:
  - `X_BEARER_TOKEN=...`
- API host: defaults to `api.x.com` (configurable via `X_API_BASE`).
- The app calls these v2 endpoints:
  - `GET /2/users/by/username/:username`
  - `GET /2/users/:id/tweets?tweet.fields=created_at,author_id,text`
- Run ingestion to verify:
  - `python -m e_brain.cli ingest-x --accounts accounts-to-follow.md --max 5`

Posting (user-context; OAuth 1.0a)
- The publisher is scaffolded and currently does not sign requests (it logs `x_posting_not_implemented_oauth_signature`). Keep `DRY_RUN=true` to avoid attempts.
- When you add OAuth 1.0a signing, set:
  - `X_API_KEY` (Consumer API Key)
  - `X_API_SECRET` (Consumer API Secret)
  - `X_ACCESS_TOKEN` (Access Token for the posting account)
  - `X_ACCESS_TOKEN_SECRET` (Access Token Secret)
- Planned endpoint for posting: `POST /2/tweets` with properly signed user-context auth.

## OpenAI Setup
- Set `OPENAI_API_KEY`.
- Optionally change `EMBEDDING_MODEL` and `CHAT_MODEL`.
- Ensure `EMBEDDING_DIM` matches your embedding model.
- Test embedding path:
  - After ingesting, run: `python -m e_brain.cli embed`
  - Then generate: `python -m e_brain.cli generate --theme "neuroscience general facts"`

## RSS/Blog Ingestion

Dependencies
- Install new libs for RSS ingestion: `pip install -r requirements.txt` (adds `feedparser`, `requests`, `beautifulsoup4`).

Usage
- Default curated feeds are built-in (Nature Neuroscience, Frontiers, JNeurosci, MIT News, Stanford Neuroscience, Neuromatch, CNS, arXiv cs.AI, Distill, DeepMind).
- Run: `python -m e_brain.cli ingest-rss --max 20`
- Optional filters and custom feeds file:
  - `python -m e_brain.cli ingest-rss --feeds-file myfeeds.txt --filter "(neuro|brain|AI)"`

Notes
- Run `python -m e_brain.cli init-db` once to ensure the `raw_items.meta` column exists.
- Full-text extraction uses a lightweight cleaner; some sites may produce shorter text.

## Posting Windows
- The scheduler respects your window based on timezone passed to `publish` (default `US/Eastern`).
- Configure windows via:
  - `POST_WINDOWS_US=09:00-12:00,17:00-19:00`
  - `POST_WINDOWS_EU=08:00-11:00,18:00-20:00`
- Publish runner:
  - `python -m e_brain.cli publish --limit 3 --tz US/Eastern`

## Quick Start Checklist
1) Create `.env` from `.env.example` and fill values (OpenAI, Neon `DATABASE_URL`, X tokens).
2) Initialize DB (creates pgvector extension + tables): `python -m e_brain.cli init-db`.
3) Ingest X accounts: `python -m e_brain.cli ingest-x`.
4) Embed and generate: `python -m e_brain.cli embed` then `python -m e_brain.cli generate --theme ...`.
5) Keep `DRY_RUN=true` until posting is fully configured with OAuth signing.
