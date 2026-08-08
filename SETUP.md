# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md

# Setup Guide

Step-by-step instructions for connecting Ghost, payment providers, and deploying the Cloudflare Worker proxy.

---

## Contents

- [Signing in](#signing-in)
- [Infrastructure overview](#infrastructure-overview)
- [Ghost connection](#ghost-connection)
- [Polar](#polar)
- [Lemon Squeezy](#lemon-squeezy)
- [PayPal](#paypal)
- [Cloudflare Worker proxy](#cloudflare-worker-proxy)

---

## Signing in

You choose this once, on the first run, and it is the only part of PayGlue that
works differently depending on how you run it. Everything else, including
running several publications of your own, is the same either way.

### Accounts kept by this installation

The default. `LOCAL_AUTH_ENABLED=1`, which is what `docker-compose.yml` sets, and
nothing else to configure. The first time you open the dashboard it asks you to
create an account, and that screen closes for good the moment one exists.

The check for that is a count of the rows in your database, not a flag the
browser sends. An installation that faces the internet with an open
registration endpoint is the easiest way there is to lose it, so there is no way
to reopen that screen short of emptying the table yourself.

Everyone after the first person arrives by invitation.

**Configure outbound mail, or accept the consequence.** A password reset is sent
by email. Without a working mail setup, a forgotten password can only be fixed
from the command line:

```bash
docker compose exec web python manage.py shell -c "
from payglue_backend.tenants.models import UserProfile
from payglue_backend.authn import local_identity
local_identity.set_password(UserProfile.objects.get(email='you@example.com'), 'a-new-password')
"
```

That is fine on your own machine. On a server with other people on it, set
`RESEND_API_KEY` or point `EMAIL_BACKEND` at your own SMTP before you invite
anybody.

**What you do not get:** authenticator apps, magic links, and sign-in with
Google or GitHub. Those are features of a hosted identity provider, and half an
implementation would be worse than none, so the dashboard leaves those sections
out entirely rather than showing buttons that fail. Confirming something
destructive still asks for a second factor: it falls back to a one-time code by
email.

Passwords are checked against Django's standard validators. At least ten
characters, not entirely numeric, not too close to your email address, and not
one of the twenty thousand that appear in every leak.

### A hosted identity provider

Set `LOCAL_AUTH_ENABLED=0` and point the backend at your own Supabase project,
or any issuer that publishes a JWKS endpoint:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWKS_URL=https://your-project.supabase.co/auth/v1/.well-known/jwks.json
```

The dashboard needs two more, and these are read **when it is built**, not when
it runs, so they belong in `frontend/.env` and take effect after a rebuild:

```bash
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-publishable-key
```

The publishable key is the one meant for the browser and ships inside the
bundle. The service role key does not belong here.

With this you get authenticator apps, magic links, and social sign-in, and you
create your first account in the provider itself rather than in the wizard.

### Switching later

Both are the same application, so switching is a configuration change and a
restart. What does not travel is the accounts: a password kept here is not
known to a hosted provider, and the other way round. Whoever signed in one way
signs up again the other way.

---

## Infrastructure overview

PayGlue needs four things running before you connect any payment provider:

| Component | Purpose | Recommended options |
|---|---|---|
| PostgreSQL | Main database | Neon (free tier), Supabase (free tier), Railway, self-hosted |
| Redis | Celery task queue and cache | Upstash (free tier), Railway, self-hosted |
| Auth (JWT/JWKS) | Dashboard login | Supabase Auth (free tier), self-hosted GoTrue |
| Backend host | Runs Django + Celery | Railway, Render, Fly.io, any VPS with Docker |

For a fully local setup, `docker compose up` brings up PostgreSQL and Redis automatically. You still need a JWT issuer for dashboard auth — Supabase free tier covers this without additional cost.

### Deployment tips

**Railway** is the fastest path if you want everything managed: connect the repo, set environment variables, and Railway handles builds, restarts, and zero-downtime deploys. Add a Redis and Postgres service in the same project.

**Render** is a strong alternative. Free tier works for low-traffic self-hosted setups; paid plans add background workers (needed for Celery).

**Fly.io** gives you more control over regions and is well-suited if you want your backend close to your Ghost instance geographically.

**VPS (Hetzner, DigitalOcean, Contabo, etc.)** is the most private option. Run everything with Docker Compose. You manage updates and restarts yourself, but nothing runs on someone else's platform.

---

## Ghost connection

### What you need

- A self-hosted Ghost instance (any version)
- Ghost Admin API key (created in Ghost Admin under Integrations)

### Steps

1. In Ghost Admin, go to **Settings > Integrations > Add custom integration**
2. Give it a name (e.g. "PayGlue") and copy the **Admin API key**
3. In the PayGlue dashboard, open **Settings > Ghost Connection**
4. Enter your Ghost site URL (e.g. `https://yourblog.com`) and the Admin API key
5. Click **Verify** — PayGlue checks that the PayGlue script tag is present in your Ghost theme

### Install the header script

PayGlue needs a small script tag in your Ghost theme's `<head>`. Go to **Settings > Installation** in the PayGlue dashboard to get your snippet, then add it to your Ghost theme via **Ghost Admin > Settings > Code injection > Site header**.

---

## Polar

### What you need

- A Polar account at [polar.sh](https://polar.sh)
- An organization with at least one product or subscription plan

### Steps

1. In Polar, go to **Settings > Preferences > Developers** and create a new API token
   - Set expiration to **Never**
   - Required scopes: `products:read`, `orders:read`, `subscriptions:read`
2. In Polar, go to **Webhooks** and create a new endpoint
   - URL: the webhook URL shown in the PayGlue dashboard under **Connections > Polar**
   - Events to enable: `order.paid`, `subscription.created`, `subscription.updated`, `subscription.revoked`
   - Copy the **webhook secret**
3. In the PayGlue dashboard, open **Connections > Polar**
4. Enter your API token and webhook secret, then save
5. Go to **Mappings** and map each Polar product to a Ghost membership tier

---

## Lemon Squeezy

### What you need

- A Lemon Squeezy account at [lemonsqueezy.com](https://www.lemonsqueezy.com)
- At least one store with a product or subscription

### Steps

1. In Lemon Squeezy, go to **Settings > API** and create a new API key
2. In Lemon Squeezy, go to **Settings > Webhooks** and add a new webhook
   - URL: the webhook URL shown in the PayGlue dashboard under **Connections > Lemon Squeezy**
   - Events to enable: `order_created`, `subscription_created`, `subscription_updated`, `subscription_expired`
   - Copy the **signing secret**
3. In the PayGlue dashboard, open **Connections > Lemon Squeezy**
4. Enter your API key, store ID, and signing secret, then save
5. Go to **Mappings** and map each Lemon Squeezy product to a Ghost membership tier

---

## PayPal

### What you need

- A **PayPal Business account** (personal accounts are not supported)
- Live credentials only (PayPal sandbox events cannot be cryptographically verified)
- A subscription plan created in the PayPal dashboard (PayPal does not support one-time product purchases through PayGlue)

### Steps

1. Go to [developer.paypal.com](https://developer.paypal.com) and log in with your Business account
2. Under **My Apps & Credentials**, switch to **Live** (not Sandbox) and create a new app
   - Copy the **Client ID** and **Client Secret**
3. In the PayGlue dashboard, open **Connections > PayPal**
4. Enter your Client ID and Client Secret, then save
5. PayGlue generates a webhook URL — copy it
6. Back in the PayPal developer dashboard, go to your app and add the webhook URL
   - Events to enable: `BILLING.SUBSCRIPTION.ACTIVATED`, `BILLING.SUBSCRIPTION.CANCELLED`, `BILLING.SUBSCRIPTION.EXPIRED`
   - Copy the **Webhook ID** shown after saving
7. Enter the Webhook ID in the PayGlue dashboard and save
8. Go to **Mappings** and map each PayPal subscription plan to a Ghost membership tier

> Customers must have a PayPal account to subscribe. PayPal is a payment processor, not a product platform — buyers complete checkout at `paypal.com` and are redirected back afterward.

---

## Cloudflare Worker proxy

The Cloudflare Worker acts as a secure reverse proxy between payment providers and your Django backend. Providers send webhooks to a public URL (e.g. `api.your-domain.com`), and the Worker forwards them to your backend with an authentication token.

### What you need

- A Cloudflare account with your domain added
- [Wrangler CLI](https://developers.cloudflare.com/workers/wrangler/) installed (`npm install -g wrangler`)

### Steps

1. Clone the repo and navigate to the Worker directory:
   ```bash
   cd workers/api-proxy
   ```

2. Edit `wrangler.toml` with your values:
   ```toml
   [vars]
   SUPABASE_PROJECT_REF = "your-supabase-project-ref"
   RAILWAY_BACKEND_URL  = "https://your-backend.example.com"

   [[routes]]
   pattern = "api.your-domain.com/*"
   zone_name = "your-domain.com"
   ```

3. Set secrets (these are not stored in `wrangler.toml`):
   ```bash
   wrangler secret put WEBHOOK_ENDPOINT_TOKEN
   ```

4. Deploy:
   ```bash
   wrangler deploy
   ```

5. In your `.env`, set `WEBHOOK_ENDPOINT_TOKEN` to the same value you used in step 3.

### How the proxy works

All requests to `api.your-domain.com` are forwarded to your backend. The Worker adds the `WEBHOOK_ENDPOINT_TOKEN` as a header on webhook requests so the Django backend can verify they came through the proxy and not directly from the public internet.
