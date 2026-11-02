# 03: Document Railway dashboard deployment

**What to build:** The user can follow a verified guide from a tested source
revision through Railway dashboard configuration, private health checks,
persistent-cache verification, and recovery from a failed deployment.

**Blocked by:** 01: Docker packaging; 02: Linux verification and CI evidence.

**Status:** ready-for-agent

Source: [Deployment specification](../spec.md).

## Acceptance criteria

- [ ] The guide covers connecting `srombs/nasa_rag` from the repository root on
  `main`, enabling GitHub autodeploys, Dockerfile detection, and retaining the
  image's start command. Link it from the root README and API documentation.
- [ ] Explain which files Railway reads automatically, which settings the user
  saves in the dashboard, and that the Markdown spec is not runtime config.
  Optional infrastructure-as-code capture requires explicit plan/apply; it is not
  part of normal application autodeploy. Verify current official configuration
  guidance before writing platform-specific instructions.
- [ ] Supply the dashboard checklist: `/health`, initial 300-second readiness
  allowance, restart on failure with at most three retries, one replica/worker,
  one region, a writable `/data` volume, and no public domain or TCP proxy.
- [ ] Document runtime variables and adding the OpenAI key through the dashboard,
  without placing actual credentials in the repository. Explain first-start paid
  embeddings, cache reuse, volume permissions, and runtime-only volume access.
- [ ] Describe resource sizing from ticket 02's measurements and their limits.
  Identify region, sleep/always-on behavior, and compute alerts/budget settings as
  operator choices; do not invent a settled budget or treat Railway limits as an
  external OpenAI spending cap.
- [ ] Explain enabling **Wait for CI**, private in-container health checks,
  restart/cache verification, safe logs, brief volume redeployment downtime, and
  recovery by deploying a known good revision while preserving stored data.
- [ ] Explain that private DNS is accessible only within the same Railway
  environment and that the portfolio needs later server-side integration.
  Public repository visibility does not expose a private service automatically.
- [ ] Distinguish completed build/mock checks from pending live-provider and
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

## Comments

2026-10-30: Specified and queued behind tickets 01–02; implementation not started.
