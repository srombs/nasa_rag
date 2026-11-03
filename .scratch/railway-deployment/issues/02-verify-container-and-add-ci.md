# 02: Verify Linux containers and add CI

**What to build:** A developer can verify the actual Linux container offline,
including cache reuse after restart, and see automated build and regression
checks on each proposed change.

**Blocked by:** 01: Package the API for Docker.

**Status:** resolved

Source: [Deployment specification](../spec.md).

**Verification state:** Actual Linux image/runtime checks and the hosted workflow
passed in [run 41704044621](https://github.com/srombs/nasa_rag/actions/runs/41704044621).
Linux process/cgroup measurements and their limitations are recorded in the
[verification guide](../../../docs/container-verification.md).

## Acceptance criteria

- [x] Container checks build ticket 01's production image without credentials,
  import the installed package and FAISS, and locate the four bundled documents.
- [x] Runtime checks exercise the actual API with provider calls mocked. Verify
  a supplied port, readiness after initialization, one active pipeline request,
  health without model calls, and an unchanged successful answer envelope.
  Reuse existing test helpers where appropriate rather than duplicating the
  application pipeline or weakening its contract.
- [x] Two fresh container processes use the same writable mounted cache. A warm
  restart reuses compatible document embeddings and the FAISS index, with no new
  document-embedding requests during startup or health checks. Test fixtures and
  provider substitution are isolated from production image startup.
- [x] Record Linux process memory and container memory when available using the
  existing profiling approach where practical. Identify cache state, mock usage,
  startup/request peaks, and loaded idle observations. Report unavailable metrics
  as pending rather than equating macOS RSS or cache file size to container RAM.
- [x] A GitHub Actions workflow runs on pull requests and pushes to `main`, uses
  locked web/dev dependencies, runs relevant existing tests, and builds/checks
  the Linux image. Include optional profiling-test dependencies when needed so
  the intended tests actually run. Neither provider nor deployment keys are used.
- [x] Checks fail on build, import, contract, or cache-reuse regressions. Record
  commands and results, distinguishing executed checks from pending ones. Do not
  describe a local test result as a completed GitHub-hosted workflow run.
- [x] Document the workflow name and Railway **Wait for CI** prerequisite for
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

## Answer

Implemented on `implement/railway-ticket-02`, [PR #5](https://github.com/srombs/nasa_rag/pull/5).
The `Tests and Linux container` workflow installs locked web/dev/profile extras,
runs the existing **132 mocked tests**, builds the production Dockerfile, and
verifies installed imports/documents and two fresh network-disabled containers.
The inspected production startup command runs unchanged as the probe's child;
provider mocks and lifespan observation exist only in mounted test scripts.

Actual Linux execution passed for commit `7007220` in the workflow linked above.
Both starts honored port 8765 with one worker, correctly gated readiness,
rejected a concurrent question while keeping health responsive, preserved the
successful answer/UUID/header contract, and completed graceful shutdown. Both
reused persisted embeddings/index with no startup/health model calls. Each
successful question made the expected 13 mocked provider calls.

The guide records exact commands, local versus hosted evidence, Wait for CI
prerequisites, and [raw Linux process/cgroup measurements](../../../docs/container-memory-linux.json).
Container question peaks were about 276 MiB including the probe; synthetic
warm-cache observations are not deployed Railway capacity/billing measurements.
Standards and spec reviews found no actionable issues. Production application
code and Dockerfile are unchanged; no live requests or deployment were performed.

Ticket 03 can proceed. Dashboard Wait for CI behavior and hosted readiness remain
ticket 04, including verification of the user's existing Railway deployment.

## Comments

2026-10-30: Specified and queued behind ticket 01; implementation not started.

2026-11-02: User authorized implementation on `implement/railway-ticket-02`,
created from updated `main` at `41f4f27`. Claimed for implementation. The user
reports an existing Railway deployment; hosted configuration and behavior have
not been inspected. This ticket remains offline verification and CI only.

2026-11-03: Added production-image verification, two-container warm-cache checks,
test-only provider substitution, Linux process/cgroup sampling, locked optional
profiling dependencies, and the `Tests and Linux container` workflow. Existing
tests: **132 passed**; profiling file: **3 passed**; Ruff, mypy (including Linux
platform), and diff whitespace checks pass. A local two-process trial of the
new probe passed its HTTP/cache/shutdown assertions. Actual container execution
fails explicitly because Docker is absent; Linux metrics and GitHub-hosted
results remain pending. See [verification commands and limits](../../../docs/container-verification.md).

2026-11-03: Published PR #5 and ran the Linux workflow. Fixed CI interpreter
installation and the test helper's dependency on dev-only HTTP transport using
actual runner failures; no production dependencies were added. Hosted run
41704044621 passes all tests and image/runtime checks. Saved Linux RSS/cgroup
evidence, completed both review axes without actionable findings, and resolved
ticket 02. Local Docker remains unavailable; the required image verification
was executed on GitHub's Linux runner.
