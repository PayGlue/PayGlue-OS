# Changelog

All notable changes to PayGlue-OS. The hosted product at
[payglue.io](https://payglue.io) runs the same code and keeps its own,
customer-facing changelog at [payglue.io/changelog](https://payglue.io/changelog).

## v0.4.0 — 2026-08-08

You can run this without signing up for anything.

Until now, starting your own copy meant creating a Supabase project first.
Without one the application threw while loading, so it never reached a screen
at all. That was a strange first requirement for software you were about to
run on your own machine, and it is gone.

### Accounts that live in your installation

Set `LOCAL_AUTH_ENABLED=1`, which `docker-compose.yml` now does by default,
and the accounts live in your own database. Django hashes the passwords,
Django's token generator carries the reset links, and the API issues the same
kind of bearer token it always did.

This is a branch, not a fork. `get_auth_token_verifier()` already chose
between four implementations behind one protocol; local accounts are the
fifth. A local token arrives in the same header and resolves to the same
profile through the same invite gate, so nothing downstream can tell the two
apart.

Choosing a hosted identity provider still works exactly as before, and adds
what only such a provider can: authenticator apps, magic links, and sign-in
with Google or GitHub. Screens for those are hidden where there is nothing
behind them, rather than shown and broken.

### Setup on first run

A fresh installation opens a two-step wizard instead of a sign-in page it has
no key for: pick how sign-in works, create the first account. Everything after
that is the publication and Ghost screens that were always there.

The wizard closes for good once an account exists, and that is decided by
counting rows in your database, never by anything the browser sends. Everyone
after the first person arrives by invitation.

### What the first run taught us

This release was installed twice from a clean clone before it shipped, and
that found things no test had:

- **The quickstart broke the install.** `.env.example` shipped a placeholder
  encryption key that is not a valid key, and it overrode the working default
  in `docker-compose.yml`. Copying the example file, step one of the guide,
  left you worse off than skipping it. The value now ships empty with the
  command to generate one beside it.
- **Host ports could not be changed** without editing a tracked file. Compose
  appends port lists rather than replacing them, so an override file does not
  help. They now come from the environment, with the same defaults.

### Also in this release

- **Two-factor for everyone**: `X-Frame-Options` was missing from every
  response, including the HTML the embed endpoints serve. The middleware that
  sets it was simply not in the list.
- **The full test suite ships**, 176 tests become 579. It used to be a separate
  hand-maintained copy here, which is how `main` went red for two commits
  without anyone noticing.
- **Billing, plans and affiliate screens are gone.** They were the storefront
  of the hosted service, and you have no subscription with us.
- **Creating a publication no longer needs PostgREST.**
- **A race in the setup gate is closed.** Two requests arriving together could
  both create a first account. A unique index now settles it in the database.
- The setup guide gained a chapter on signing in, and the wizard carries a
  short letter about why this project exists.

### Upgrade notes

**Run migrations.** `0044` and `0045` add local credentials and the constraint
that keeps the first account unique.

Nothing changes for an installation using a hosted identity provider. Leave
`LOCAL_AUTH_ENABLED` unset or `0` and everything works as before.

## v0.3.0 — 2026-08-06

Nothing phones home any more. A self-hosted install was quietly tied to the
hosted product: embed snippets carried a fixed `api.payglue.io` address, the
installed-check compared your site against a hostname you do not own, seeded
emails were signed with a stranger's name, and product analytics reported to
a project you have no access to.

Snippets now work out their own backend from the tag they were loaded from,
the check looks at the path rather than the host, seeded emails arrive
switched off and carry no name or links, and there is no analytics package in
the build at all.

**Re-copy your embed snippets** if you pasted any before this release.

## v0.2.0 — 2026-07-20

The first sync since June, and a big one: the dashboard was rebuilt, the
provider list nearly tripled, and the backend grew real account lifecycle
management.

### Payment providers: 3 → 8

Polar, Lemon Squeezy, and PayPal are joined by **Gumroad, Paddle, Ko-fi,
Creem, and Patreon**. Every provider ships with credential storage
(encrypted at rest), a health check, webhook verification, and product
autofetch for the mapping pickers.

### Dashboard 2.0

A visual rebuild of the entire authenticated app:

- Full **dark mode**, per-screen and consistent
- **Connections overview**: one grid with real provider logos replaces eight
  separate connection pages; provider details are config-driven
  (`lib/connectionProviders.ts`) instead of one hand-copied view per provider
- Settings, Analytics, and Features sections rebuilt on a shared component kit
- A shared UI kit under `components/ui/` (PageHeader, Card, StatCard,
  DataTable, StatusPill, Tabs, EmptyState, ...)

### Security and account lifecycle

- **Step-up confirmation** for destructive actions: an overlay asks for your
  authenticator code (or an email one-time code) instead of logging you out.
  Server-side verification against the auth provider's factors API.
- **TOTP two-factor login** with backup codes, including the login challenge
  screen
- **Account deletion that actually deletes**: a real backend endpoint with a
  cascade that removes tenants, credentials, and the auth account, in an
  order that can never leave a login pointing at deleted data
- **Team notifications**: removing a member, transferring ownership --
  everyone affected is told, each in a separate email
- Per-tenant webhook secrets, plan limits with a usage endpoint, and a
  30-day grace flow for lapsed accounts

### Support requests with reference numbers

Support requests from the dashboard are stored first, then confirmed by
email with a reference number the customer can quote. The request history
shows status only, by design.

### Housekeeping

- The pricing table embed supports free, one-time, and subscription columns
  for every provider
- The test suite survives Node 25 (its built-in `localStorage` shadows
  jsdom's; the test setup now substitutes a working implementation)
- CI: frontend typecheck + tests + build, backend tests against real Postgres

## v0.1.0 — 2026-06

Initial public release: Polar, Lemon Squeezy, and PayPal, webhook relay into
Ghost's Admin API, buy buttons, paywalls, and the first pricing table.
