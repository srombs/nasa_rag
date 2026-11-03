# 03: Document Railway dashboard deployment

**What to build:** The user can follow a verified guide from a tested source
revision through Railway dashboard configuration, private health checks,
persistent-cache verification, and recovery from a failed deployment.

**Blocked by:** 01: Docker packaging; 02: Linux verification and CI evidence.

**Status:** ready-for-agent

**Resolution:** resolved

Source: [Deployment specification](../spec.md).

## Acceptance criteria

- [x] The guide covers connecting `srombs/nasa_rag` from the repository root on
  `main`, enabling GitHub autodeploys, Dockerfile detection, and retaining the
  image's start command. Link it from the root README and API documentation.
- [x] Explain which files Railway reads automatically, which settings the user
  saves in the dashboard, and that the Markdown spec is not runtime config.
  Optional infrastructure-as-code capture requires explicit plan/apply; it is not
  part of normal application autodeploy. Verify current official configuration
  guidance before writing platform-specific instructions.
- [x] Supply the dashboard checklist: `/health`, initial 300-second readiness
  allowance, restart on failure with at most three retries, one replica/worker,
  one region, a writable `/data` volume, and no public domain or TCP proxy.
- [x] Document runtime variables and adding the OpenAI key through the dashboard,
  without placing actual credentials in the repository. Explain first-start paid
  embeddings, cache reuse, volume permissions, and runtime-only volume access.
- [x] Describe resource sizing from ticket 02's measurements and their limits.
  Identify region, sleep/always-on behavior, and compute alerts/budget settings as
  operator choices; do not invent a settled budget or treat Railway limits as an
  external OpenAI spending cap.
- [x] Explain enabling **Wait for CI**, private in-container health checks,
  restart/cache verification, safe logs, brief volume redeployment downtime, and
  recovery by deploying a known good revision while preserving stored data.
- [x] Explain that private DNS is accessible only within the same Railway
  environment and that the portfolio needs later server-side integration.
  Public repository visibility does not expose a private service automatically.
- [x] Distinguish completed build/mock checks from pending live-provider and
  hosted observations. Include an operator checklist for ticket 04 and local
  container commands consistent with the actual Dockerfile and tests.

## Verification

Check repository links, paths, commands, environment names, and CI workflow names
against tickets 01–02. Verify platform-specific guidance against current official
Railway docs. No deployment or live model request is needed to write the guide.

## Scope

Documentation only. The user owns dashboard configuration in ticket 04. Optional
infrastructure-as-code implementation, website UI, proxy deployment, and changes
to the application contract remain deferred.

## Answer

Implemented [the Railway dashboard deployment guide](../../../docs/railway-deployment.md)
on `implement/railway-ticket-03`, with links from the root README, API guide, and
Docker guide. The guide covers GitHub/Docker setup, runtime variables, private
networking, readiness/restart controls, `/data` persistence, resource/lifecycle
choices, Wait for CI, safe logs, recovery, and the ticket 04 operator record.
Official Railway guidance was checked on 2026-11-03; links sit beside the relevant
instructions. Hosted configuration and live-provider observations remain pending.

Verification:

- `uv sync --locked --extra web --extra dev --extra profile`: passed.
- `uv run --no-sync python -m pytest -q tests/test_web_runtime.py`: **3 passed**.
- `uv run --no-sync python -m pytest -q`: **132 passed**.
- `uv run --no-sync ruff check scripts tests/test_web_runtime.py`: passed.
- `uv run --no-sync mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts`:
  passed, five source files.
- Relative documentation links/anchors and executable shell syntax: passed.
  Both Python snippets ran with offline fixtures; checked runtime-port health
  targeting, canonical embedding hashes, ledger counts, and missing-cache failure.
  This is snippet verification, not a hosted health/cache observation.
- `git diff --check`: passed. No production code or dependencies changed.

Standards review identified a triage/lifecycle mismatch. Retained the configured
`ready-for-agent` triage role and recorded completion separately in `Resolution`
above; the roadmap reflects completed progress. Spec review found no actionable
issues. No deployment, live model request, or push was performed. Ticket 04 still
requires the implementation to be published, matching CI evidence, and the user's
dashboard configuration and observations.

## Comments

2026-10-30: Specified and queued behind tickets 01–02; implementation not started.

2026-11-03: User authorized implementation after pulling `main`. Claimed on
`implement/railway-ticket-03`, based on updated `main` at `7922466`. Scope is the
deployment guide and repository handoff; dashboard work remains ticket 04.

2026-11-03: Completed documentation and verification. Completion is recorded in
`Resolution` separately from the five configured triage roles in `Status`.
