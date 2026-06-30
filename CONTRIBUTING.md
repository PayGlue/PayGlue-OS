# Contributing to PayGlue-OS

Thanks for your interest in contributing. Contributions of any kind are welcome — bug fixes, new payment provider adapters, documentation improvements, and tests.

If you contribute and want to run PayGlue on your own Ghost site using our hosted infrastructure, reach out at [team@payglue.io](mailto:team@payglue.io). Contributors get a goodie.

---

## Getting started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Make your changes
4. Run the backend tests: `cd backend && python -m pytest`
5. Push your branch and open a pull request

---

## Opening issues

Before opening a pull request for a non-trivial change, open a GitHub issue first to describe what you want to build or fix. This avoids duplicate work and lets us give early feedback.

For bug reports, include:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (OS, Python version, Docker version)

Security vulnerabilities should not be reported as public issues. See [SECURITY.md](SECURITY.md) for the private disclosure process.

---

## Pull request guidelines

- One feature or fix per PR — keep changes focused
- Link the GitHub issue in the PR description (`Closes #123`)
- Add or update tests when changing behavior
- Update `SETUP.md` if your change affects the setup process
- Keep commit messages clear and in the imperative: "Add PayPal adapter" not "Added paypal stuff"

---

## Adding a new payment provider

Payment providers are implemented as adapters in `backend/src/payglue_backend/webhooks/adapters/`. Each adapter handles two things:

1. **Signature verification** — cryptographically verify the incoming webhook payload against the provider's secret
2. **Event mapping** — translate provider-specific event types into PayGlue's internal event format (`order.paid`, `subscription.created`, etc.)

The Polar adapter (`adapters/polar.py`) and Lemon Squeezy adapter (`adapters/lemon_squeezy.py`) are the cleanest references to follow. Each adapter is registered in `webhooks/wiring.py`.

A new provider PR should include:
- The adapter file under `adapters/`
- Registration in `wiring.py`
- Unit tests under `backend/tests/unit/`
- A setup section in `SETUP.md`

---

## Seed data

Seed data refers to a minimal set of database records that puts the application into a working state for local development and testing — for example, a tenant, a connected Ghost site, a product mapping, and a test webhook event.

PayGlue does not ship a seed script in this repository. To populate your local environment:

1. Start the backend with `docker compose up`
2. Use the dashboard UI to create a tenant and connect your local Ghost instance (see `SETUP.md`)
3. Use the webhook smoke test in `README.md` to send a test event

If you are writing tests, the backend test suite uses Django's test client and creates fixtures inline — see `backend/tests/` for examples.

---

## Code style

- Python: follow the existing style; run `ruff check .` before pushing
- TypeScript/Vue: run `npm run lint` in the `frontend/` directory
- No new comments explaining what code does — only add comments for non-obvious constraints or workarounds
