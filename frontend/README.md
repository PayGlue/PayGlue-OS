# Ghost Glue Frontend

Vue 3 + Vite + Tailwind CSS self-service portal for:

- tenant workspace selection,
- product mapping management,
- tenant team management,
- Ghost pricing table builder and embed snippet generation.

## Run locally

Install dependencies:

```bash
npm install
```

Start dev server:

```bash
npm run dev
```

Build production bundle:

```bash
npm run build
```

Run tests:

```bash
npm run test
```

## API base URL

The app defaults to same-origin API calls. For local split-host development, set:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

When running in Docker (`make docker`), frontend dev server proxies `/api` and `/t` to the backend service automatically.

## Current routes

- `/`
- `/login`
- `/signup`
- `/tenant/select`
- `/t/:tenantSlug/mappings`
- `/t/:tenantSlug/team`
- `/t/:tenantSlug/pricing`

## Notes

- Authentication is passwordless magic link only; invite validation happens before account creation.
- Role-based editing is enforced in the UI and again by backend APIs.
