# 02: Verify Linux containers and add CI

**What to build:** A developer can verify the actual Linux container offline,
including cache reuse after restart, and see automated build and regression
checks on each proposed change.

**Blocked by:** 01: Package the API for Docker.

**Status:** ready-for-agent

Source: [Deployment specification](../spec.md).

## Acceptance criteria

- [ ] Container checks build ticket 01's production image without credentials,
  import the installed package and FAISS, and locate the four bundled documents.
- [ ] Runtime checks exercise the actual API with provider calls mocked. Verify
  a supplied port, readiness after initialization, one active pipeline request,
  health without model calls, and an unchanged successful answer envelope.
  Reuse existing test helpers where appropriate rather than duplicating the
  application pipeline or weakening its contract.
- [ ] Two fresh container processes use the same writable mounted cache. A warm
  restart reuses compatible document embeddings and the FAISS index, with no new
  document-embedding requests during startup or health checks. Test fixtures and
  provider substitution are isolated from production image startup.
- [ ] Record Linux process memory and container memory when available using the
  existing profiling approach where practical. Identify cache state, mock usage,
  startup/request peaks, and loaded idle observations. Report unavailable metrics
  as pending rather than equating macOS RSS or cache file size to container RAM.
- [ ] A GitHub Actions workflow runs on pull requests and pushes to `main`, uses
  locked web/dev dependencies, runs relevant existing tests, and builds/checks
  the Linux image. Include optional profiling-test dependencies when needed so
  the intended tests actually run. Neither provider nor deployment keys are used.
- [ ] Checks fail on build, import, contract, or cache-reuse regressions. Record
  commands and results, distinguishing executed checks from pending ones. Do not
  describe a local test result as a completed GitHub-hosted workflow run.
- [ ] Document the workflow name and Railway **Wait for CI** prerequisite for
  ticket 03. Do not add infrastructure apply automation or deploy from CI.

## Verification

Run the existing test suite and the new container checks against the same image
that production uses. Record Linux measurements with their limitations. Run the
workflow on GitHub when the implementation is published; until then, leave that
hosted result pending. Missing container tooling does not satisfy the acceptance
criteria; use the Linux CI runner when available.

## Scope

Offline verification and CI only. No live model requests, Railway provisioning,
website changes, or model/retrieval tuning. Hosted readiness and **Wait for CI**
behavior are verified during ticket 04, after dashboard configuration exists.

## Comments

2026-10-30: Specified and queued behind ticket 01; implementation not started.
