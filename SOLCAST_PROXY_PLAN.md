# Solcast Proxy Cache Service

## Overview
Build a small FastAPI service that proxies Solcast forecasts with a SQLite-backed cache, refreshing on a configurable schedule (default 4h), packaged for Docker.

## Architecture
- FastAPI app (`solcast_proxy/app.py`) with `GET /forecasts` mirroring `get_solcast_data` from `api_handlers.py`.
- Upstream client: `httpx` with timeout/retries.
- Storage: SQLite via `aiosqlite` (`cache` table for JSON payloads).
- Background refresher: async loop that refreshes configured keys every N hours (default 4).
- Config via env vars using `pydantic` `BaseSettings`.

## Data model (SQLite)
- Table `cache`
  - `key` TEXT PRIMARY KEY (request signature; fixed Solcast URL incl query)
  - `value` TEXT NOT NULL (raw JSON)
  - `fetched_at` DATETIME NOT NULL (UTC)
- Optional index on `fetched_at`.

## Caching strategy
- Cache-aside:
  - On request: return cached if `now - fetched_at <= CACHE_TTL_HOURS`.
  - If stale/miss: fetch upstream; on success upsert and return.
  - If upstream fails but cache exists: serve stale up to `MAX_STALE_HOURS` with `X-Cache: stale`.
- Background refresh:
  - Periodically refresh the single key on a schedule, with small jitter.

## API
- GET `/forecasts`
  - Calls Solcast URL with `format=json` and `SOLCAST_API_KEY` from env.
  - Returns JSON; headers: `X-Cache: hit|miss|stale`, `X-Fetched-At: <utc-iso>`.
- GET `/healthz`
  - Returns status and last refresh timestamp.
- (Optional) GET `/metrics`

## Refresh logic
- Startup task: asyncio loop that sleeps `REFRESH_INTERVAL_HOURS`, then refreshes.
- Use retries with backoff and timeouts; log failures.

## Configuration (env)
- `SOLCAST_API_KEY` (required)
- `SOLCAST_URL` (default: https://api.solcast.com.au/rooftop_sites/6803-0207-f7d6-3a1f/forecasts)
- `REFRESH_INTERVAL_HOURS` (default 4)
- `CACHE_TTL_HOURS` (default 4)
- `MAX_STALE_HOURS` (default 24)
- `DB_PATH` (default `/data/cache.db`)
- `HTTP_TIMEOUT_S` (default 15)

## Files to add
- `solcast_proxy/app.py`: FastAPI app, endpoints, startup/shutdown, background task.
- `solcast_proxy/config.py`: pydantic settings loader.
- `solcast_proxy/db.py`: SQLite init and CRUD (get, upsert).
- `solcast_proxy/client.py`: httpx client with retries/backoff.
- `solcast_proxy/models.py`: optional pydantic models (or pass-through JSON).
- `Dockerfile`: multi-stage, install with `uv`, run `uvicorn`.
- `docker-compose.yml`: service + volume `/data`; env file binding; healthcheck to `/healthz`.
- `.env.example`: sample env values.
- `.gitignore`: includes `.venv`, `.env`, `/debug/`.
- `pyproject.toml`: managed by `uv`; deps: fastapi, uvicorn[standard], httpx, aiosqlite, pydantic-settings, python-dotenv, backoff (optional).

## Docker
- Run as non-root; mount named volume at `/data` for SQLite persistence.
- One worker (`--workers 1`) due to SQLite writer; scale later by moving to Postgres.

## Observability
- Structured logging with upstream latency and cache status.
- Return stale on upstream failures; log warnings.

## Security
- Never expose `SOLCAST_API_KEY` in responses.
- Optionally protect endpoints with internal token if exposed publicly.

## Minimal schema
```sql
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  fetched_at DATETIME NOT NULL
);
```

## Implementation todos
1. Scaffold FastAPI service under `solcast_proxy/` with uv config
2. Implement pydantic settings for env vars and defaults
3. Create SQLite init and cache table, connection management
4. Implement get/upsert cache by key with `aiosqlite`
5. Implement `httpx` client with retries/backoff and timeouts
6. Create `GET /forecasts` with cache-aside and headers
7. Add async refresher loop honoring `REFRESH_INTERVAL_HOURS`
8. Add `/healthz` reporting last refresh and db status
9. Create `Dockerfile` and `docker-compose.yml` with volume and envs
10. Add `.env.example` and brief README usage notes
11. Add structured logging (include cache status and timings)


