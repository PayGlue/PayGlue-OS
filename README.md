# PayGlue-OS

**PayGlue connects Ghost CMS to any payment provider.**

Ghost natively supports only Stripe. PayGlue bridges Polar, Lemon Squeezy, PayPal, and more by receiving signed webhooks and syncing membership state back into Ghost via the Admin API. No Ghost code changes required.

> **Open beta.** Version 0.2 covers eight payment providers -- Polar, Lemon Squeezy, PayPal, Gumroad, Paddle, Ko-fi, Creem, and Patreon -- plus free member signups through Ghost. See the [changelog](CHANGELOG.md) for what changed.
>
> **Rather not run it yourself?** [payglue.io](https://payglue.io) is the hosted version, operated by the person who built this. Same code you are looking at, minus the ops.
>
> One more thing: somewhere in this source code hides a small thank-you for people who actually read it. Happy hunting.

---

## Why this exists

I run a Ghost blog and wanted to accept payments through Polar, not Stripe. Ghost made that impossible without custom code. So I built PayGlue to solve my own problem, then realized others had the same frustration. This is that tool, now open source.

---

## See it live

Try it before setting anything up:

| Demo | What it shows |
|---|---|
| [Full pricing table](https://blog.payglue.io/what-a-full-pricing-table-looks-like-when-it-talks-to-ghost/) | Embedded in a Ghost post, live sandbox checkout |
| [Paywall in action](https://blog.payglue.io/how-this-blog-runs-with-a-payglue-paywall/) | How this blog gates content with PayGlue |
| [Three buttons, one dashboard](https://blog.payglue.io/three-buttons-one-dashboard-how-we-embed-payment-links-in-this-blog/) | Embedded payment links in Ghost |
| [go.payglue.io/membership](https://go.payglue.io/membership) | Production German tech blog using PayGlue live |

---

## How it works

PayGlue sits between your payment provider and Ghost:

1. Customer buys through any of the eight supported providers
2. Provider sends a signed webhook to PayGlue
3. PayGlue verifies the cryptographic signature and maps the product to a Ghost membership tier
4. Ghost Admin API creates or updates the member automatically

---

## Supported providers

| Provider | Status |
|---|---|
| Polar | Available |
| Lemon Squeezy | Available |
| PayPal | Available |
| Gumroad | Available |
| Paddle | Available |
| Ko-fi | Available |
| Creem | Available |
| Patreon | Available |
| Mollie | On hold -- its recurring model needs per-creator subscription code, which does not fit the webhook-relay approach |

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Vue 3 + TypeScript, Cloudflare Pages |
| Backend | Django + Celery, Python 3.12+ |
| Auth | Supabase Auth (ES256 JWT) |
| Database | PostgreSQL |
| Queue / Cache | Redis |
| Webhook proxy | Cloudflare Workers |

---

## Self-hosting

### Prerequisites

- Docker and Docker Compose
- A running Ghost instance (any self-hosted version)
- PostgreSQL (see recommended services below)
- Redis (see recommended services below)
- A Supabase project or compatible auth backend (see below)
- An account with at least one payment provider

### Recommended services

PayGlue has no hard dependency on any specific cloud provider. The table below lists what each component needs and some options for each:

| Component | What you need | Options |
|---|---|---|
| PostgreSQL | A Postgres database | Neon, Railway, Supabase, self-hosted |
| Redis | A Redis instance | Upstash, Railway, self-hosted |
| Auth | JWT issuer (ES256, JWKS endpoint) | Supabase Auth (recommended), self-hosted GoTrue, Clerk |
| Deployment | Anywhere that runs Docker | Railway, Render, Fly.io, any VPS |
| Webhook proxy | Routes provider webhooks to your backend | Cloudflare Workers (included), any reverse proxy |

For a fully self-hosted setup (no external services), Docker Compose brings up PostgreSQL, Redis, and the Django backend locally. Auth requires a JWT issuer with a JWKS endpoint; self-hosted Supabase or GoTrue covers that.

### 1. Clone and configure

```bash
git clone https://github.com/PayGlue/PayGlue-OS.git
cd PayGlue-OS
cp .env.example .env
```

Fill in your `.env`:

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Required with `DJANGO_DEBUG=0`; the app refuses to boot without it |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames the API answers on |
| `DATABASE_URL` | Postgres connection string |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis URLs (there is no `REDIS_URL`) |
| `CREDENTIAL_ENCRYPTION_KEY` | 32-byte base64 key: `openssl rand -base64 32` |
| `SUPABASE_URL` | Your Supabase project URL (or compatible auth issuer) |
| `SUPABASE_JWKS_URL` | JWKS endpoint of that project; or inline the JSON via `SUPABASE_JWKS_KEYS` |
| `WEBHOOK_ENDPOINT_TOKEN` | Random secret: `openssl rand -base64 32` |
| `WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN` | Set to `1` for single-operator deployments |
| `DJANGO_DEBUG` | Must be `0` in production |

Optional: `RESEND_API_KEY` for outbound email (or point `EMAIL_BACKEND` at Django's console backend for development), `SUPABASE_SERVICE_ROLE_KEY` for account deletion and user provisioning. The full annotated list lives in [`.env.example`](.env.example).

### 2. Start the backend

```bash
docker compose up -d postgres redis
docker compose run --rm web python manage.py migrate
docker compose up -d
```

Services:

| Service | URL |
|---|---|
| Django API | `http://localhost:8000` |
| Vue dashboard | `http://localhost:5173` |

### 3. Connect Ghost

In the PayGlue dashboard, go to Settings and paste your Ghost site URL and Admin API key. PayGlue will verify the connection by checking for the header script on your Ghost site.

<img width="3160" height="1846" alt="payglue-os-ghost-cms-connection" src="https://github.com/user-attachments/assets/b3c65037-36df-4394-8b2c-c7553fb201e9" />


### 4. Connect a payment provider and map your products

Each provider needs three things in the PayGlue dashboard: API credentials, a webhook secret, and a product mapping to a Ghost membership tier. The full step-by-step for each provider is in [SETUP.md](SETUP.md).

<img width="3248" height="1934" alt="payglue-os-payment provider-polar" src="https://github.com/user-attachments/assets/6a2c4c4e-83e5-4ad4-8782-176f21834268" />

<img width="3248" height="1934" alt="payglue-os-paywall-demo" src="https://github.com/user-attachments/assets/bbcb59b3-98ae-467f-ab13-83b6a2f3c82e" />

### 5. See it live on your website

PayGlue embeds directly into your Ghost site. Add a payment button or a full pricing table to any post or page with a single line of HTML. No iframes from third parties, no redirects away from 
your site.

<img width="3248" height="1934" alt="payglue-os-paywall-blog" src="https://github.com/user-attachments/assets/01a494f1-d718-46aa-abd5-d4ba70d367e4" />

### 6. What happens after a new membership for your publication arrives

When a customer completes a purchase, PayGlue receives the signed webhook from your payment provider, verifies the signature, and creates or updates the member in Ghost automatically. No manual steps, no code. The new member appears in your Ghost Admin with the correct tier and access level applied.

<img width="2404" height="1454" alt="payglue-os-ghost-memberview" src="https://github.com/user-attachments/assets/026b433f-9cad-408b-be52-457ea8c01af7" />


### Webhook smoke test

```bash
curl -i -X POST "http://localhost:8000/t/your-tenant/webhooks/polar/dev-token/" \
  -H "Content-Type: application/json" \
  -d '{"type":"order.paid","data":{"customer":{"email":"test@example.com"}}}'
# Expected: 202 Accepted
```

---

## Contributing

Contributions are more than welcome and will be rewarded.

If you build something with PayGlue and want to contribute back, whether that is a new payment provider adapter, a bug fix, or a documentation improvement, get in touch. Contributors who want to run PayGlue on their own Ghost site using our infrastructure get a goodie.

Reach out: [team@payglue.io](mailto:team@payglue.io)

### How to contribute

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run backend tests: `cd backend && python -m pytest`
5. Push and open a pull request

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the full PR workflow and branch naming conventions.

### Adding a new payment provider

Payment providers are implemented as adapters in `backend/src/payglue_backend/webhooks/adapters/`. Each adapter implements signature verification and event mapping. Polar and Lemon Squeezy are the cleanest references to follow.

---

## Security

PayGlue uses a two-layer security model for inbound webhooks: a URL endpoint token (proxy authentication) and per-provider cryptographic signature verification (HMAC-SHA256 for Polar and Lemon Squeezy, RSA-SHA256 for PayPal).

See [SECURITY.md](SECURITY.md) for the full security architecture and vulnerability disclosure process.

---

## License

Business Source License 1.1. See [LICENSE.md](LICENSE.md).

Self-hosting for your own Ghost site is free. Offering PayGlue as a managed service to others requires a commercial license. Each version converts to Apache License 2.0 four years after first public release.
