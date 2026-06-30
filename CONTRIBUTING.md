# Contributing

Thanks for contributing to Ghost Glue.

## Workflow

- Linear is the operational source of truth.
- GitHub pull requests are the implementation record.
- Every change must map to a Linear issue.

## No ticket, no merge

- Do not open or merge a PR without a Linear key.
- If unplanned work appears during implementation, create a new Linear issue before merging.

## Required naming and linking

- Branch name: `gogu-<number>-short-description` (example: `gogu-7-retry-alert-fixes`)
- Commit message includes key (example: `GOGU-7: improve webhook retry classification`)
- PR title includes key (example: `GOGU-7 Improve webhook retry classification`)
- PR description includes magic-word reference (example: `Closes GOGU-7`)

## Linear magic words

- Closing words (set issue to Done on merge): `close`, `closes`, `fix`, `fixes`, `resolve`, `resolves`, `complete`, `completes`.
- Non-closing words (link without force-closing): `ref`, `refs`, `references`, `part of`, `related to`, `contributes to`, `toward`, `towards`.
- Link format can use issue key or full URL.
- Multiple issues can be linked in one PR description, for example: `Fixes GOGU-4, GOGU-7 and GOGU-9`.

## Practical defaults

- Use `Closes GOGU-<id>` for single-issue PRs.
- Use `Refs GOGU-<id>` when partial work lands and issue should remain open.
- Keep one primary issue per PR whenever possible.

## PR checklist

- Link the Linear issue in the PR.
- Describe scope and user impact.
- Add tests and docs updates when needed.
- Keep changes focused; open follow-up issues for out-of-scope tasks.
