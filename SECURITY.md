# Security Manifest

Our security manifest: [payglue.io/security](https://payglue.io/security)

## Reporting a Vulnerability

If you discover a security vulnerability, please do **not** open a public GitHub issue.

You have two options:

**Email** — send a report to [team@payglue.io](mailto:team@payglue.io) with:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

**GitHub Security Advisory** — open a [private advisory](../../security/advisories/new) directly in this repository. This creates a private fork where we can collaborate on a fix before public disclosure.

We aim to respond within 24 hours and will keep you updated as we work on a fix.

---

## Security Architecture

### Webhook Endpoint Authentication

PayGlue uses a two-layer security model for inbound webhooks:

**Layer 1 — URL endpoint token**

Each webhook URL contains a secret token:
```
/t/{tenant}/webhooks/{provider}/{token}/
```

This token is injected by the Cloudflare Worker proxy and is never exposed in the public-facing webhook URL that tenants register with their payment provider. It prevents direct access to the Django backend from actors who bypass the proxy.

**`WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN`**

In single-operator deployments (the default), one global token is shared across all tenants. This is intentional: the Cloudflare Worker is shared infrastructure and holds a single `WEBHOOK_ENDPOINT_TOKEN`. This setting enables that token to authenticate webhooks for any tenant.

This is **by design** for single-operator setups. The endpoint token is not the primary security mechanism — it is a proxy authentication layer. The real payload integrity guarantee is provided by Layer 2.

For multi-operator deployments, set `WEBHOOK_ALLOW_GLOBAL_ENDPOINT_TOKEN=0` and configure per-tenant tokens via `WEBHOOK_ENDPOINT_TOKENS`.

**Layer 2 — Provider HMAC signature verification**

Every webhook payload is cryptographically verified against the payment provider's signature before any action is taken:

| Provider | Mechanism |
|---|---|
| Polar | HMAC-SHA256 over raw body, verified against stored webhook secret |
| Lemon Squeezy | HMAC-SHA256 via `X-Signature` header |
| PayPal | RSA-SHA256 via PayPal's `verify-webhook-signature` API |

A forged or replayed webhook that does not pass provider signature verification is rejected before any Ghost membership action occurs. The endpoint token alone is not sufficient to inject fake payment events.

### Credential Storage

Payment provider credentials (API keys, webhook secrets) are encrypted at rest using a `CREDENTIAL_ENCRYPTION_KEY` before being written to the database. The encryption key is an environment variable and is never stored in the database.

### Internal API

There is no internal credential lookup endpoint exposed over HTTP. Credential access happens in-process within the Django backend only.

### Authentication

Dashboard API endpoints use JWT tokens issued by Supabase Auth (ES256 algorithm). Tokens are verified against JWKS keys and scoped to the authenticated tenant. Cross-tenant access is prevented by tenant-scoped permission classes on every view.

---

## Known Design Decisions

| Decision | Reason |
|---|---|
| Global webhook endpoint token in single-operator mode | Cloudflare Worker shared infrastructure; provider HMAC is the primary integrity guarantee |
| Webhook URLs contain a secret token segment | Prevents unauthenticated access to the Django backend if the Cloudflare proxy is bypassed |
| `DJANGO_DEBUG` must be `0` in production | Debug mode exposes internal stack traces; always set to `0` in deployed environments |
