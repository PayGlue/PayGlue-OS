# PayGlue Backend

Django backend for PayGlue -- handles webhook ingestion, tenant management, and provider credential storage.

## Full local stack with Docker (recommended)

From the repository root (`PayGlue-OS/`):

```bash
make docker
```

This starts:

- `postgres` on `localhost:5432`
- `redis` on `localhost:6379`
- Django web app on `http://localhost:8000`
- Celery worker connected to Redis

Useful commands (from repo root):

```bash
make docker-logs
make docker-down
```

The root `docker-compose.yml` wires app services with:

- `DATABASE_URL=postgresql://postgres:postgres@postgres:5432/ghost_glue`
- `CELERY_BROKER_URL=redis://redis:6379/0`
- `CELERY_RESULT_BACKEND=redis://redis:6379/1`

## Local PostgreSQL only (backend/docker-compose.yml)

Start Postgres:

```bash
cd backend
docker compose up -d postgres
```

Use Postgres via `DATABASE_URL`:

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ghost_glue
```

Or use `PG*` env vars:

```bash
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=ghost_glue
export PGUSER=postgres
export PGPASSWORD=postgres
```

Stop Postgres:

```bash
cd backend
docker compose down
```

If no `DATABASE_URL`/`PG*` vars are set, the app falls back to SQLite.
