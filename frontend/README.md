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

## Waitlist link config

Set Prefinery waitlist target URL for the public landing page:

```bash
VITE_PREFINERY_WAITLIST_URL=https://your-prefinery-waitlist-url
VITE_PREFINERY_WIDGET_SRC=https://widget.prefinery.com/widget/v2/pf3sjtie.js
```

The landing page forwards common marketing query params (`utm_*`, `ref`) to `VITE_PREFINERY_WAITLIST_URL`.
The Prefinery form widget script is loaded from `VITE_PREFINERY_WIDGET_SRC` (defaults to the value above).

## Firebase OAuth config

Set Firebase client env vars when using OAuth in local/dev:

```bash
VITE_FIREBASE_API_KEY=your-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_APP_ID=your-app-id
VITE_FIREBASE_MESSAGING_SENDER_ID=your-sender-id
VITE_ENABLE_MANUAL_TOKEN_FALLBACK=0
```

Authentication now uses Firebase magic links only.

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
