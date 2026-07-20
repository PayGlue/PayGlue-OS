# Changelog

All notable changes to PayGlue-OS. The hosted product at
[payglue.io](https://payglue.io) runs the same code and keeps its own,
customer-facing changelog at [payglue.io/changelog](https://payglue.io/changelog).

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
