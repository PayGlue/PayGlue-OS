# Ghost Glue Backend

Initial executable slice for Ghost Glue backend.

## Full local stack with Docker (recommended)

From the repository root (`ghost-glue/`):

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

## Tenant-enabled local mode (Postgres + django-tenants)

Start Postgres and export env:

```bash
cd backend
docker compose up -d postgres
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ghost_glue
export DJANGO_TENANTS_ENABLED=1
```

Run shared/public migrations:

```bash
uv run python manage.py migrate_schemas --shared
```

Create a tenant + domain (replace values as needed):

```bash
uv run python manage.py shell -c "from ghost_glue_backend.tenants.models import Tenant, TenantDomain; tenant = Tenant(slug='tenant-a', schema_name='tenant_a'); tenant.save(); TenantDomain.objects.update_or_create(domain='tenant-a.localhost', defaults={'tenant': tenant, 'is_primary': True})"
```

Run tenant-schema migrations:

```bash
uv run python manage.py migrate_schemas --tenant
```

Run tests in tenant-enabled mode (Postgres required):

```bash
uv run pytest
```

Stop Postgres:

```bash
cd backend
docker compose down
```
