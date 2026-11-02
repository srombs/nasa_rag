# 01: Package the API for Docker

**What to build:** A developer can build the existing API from a clean checkout
and run it as a production container with the bundled NASA corpus, external
credentials, and persistent storage.

**Blocked by:** None (can start immediately).

**Status:** resolved

**Verification:** Local package checks passed; Linux image build/import checks
are pending ticket 02 because this workstation has no Docker engine.

Source: [Deployment specification](../spec.md).

## Acceptance criteria

- [x] A repository-owned Docker build installs the package's web dependencies
  from the existing dependency lockfile, with a pinned supported Python
  base-image version and pinned build tooling. The
  runtime image excludes development dependencies and unnecessary build tools.
- [ ] The installed application includes all four NASA documents. Required Linux
  libraries for FAISS are explicit; the package and FAISS import in the image.
- [x] Docker build-context exclusions cover real environment files, Git metadata, local virtual
  environments, generated caches, logs, and bytecode. No keys or local embeddings
  are embedded in image layers. Public source and NASA documents remain included
  as needed for the application.
- [x] Startup launches the existing FastAPI application with one worker, honors runtime `PORT`,
  and uses a non-loopback listener compatible with the intended Railway private
  network and readiness check. Keep `--no-proxy-headers`, `--no-access-log`, and
  correct server signal delivery. Explain any address-family assumption.
- [x] Runtime defaults use the spec's persistent cache and cost-ledger locations, with
  writable directories created as needed. The runtime OpenAI key is external;
  importing/building the package never initializes the retriever or calls models.
- [x] A public environment example documents existing variables, an empty key, the
  response deadline, and empty proxy trust. Real `.env` files are Git-ignored.
  The example does not imply the application automatically loads an env file.
- [x] Local build/run instructions identify the persistent volume, custom port,
  and paid embedding behavior on a fresh runtime cache. Existing RAG/CLI code and
  API behavior remain unchanged. No legacy Railway config file is introduced.

## Verification

Build from a clean checkout without credentials or a local cache, then check
installed-package imports and bundled-data discovery inside the Linux image.
Record exact commands and results. If no Docker engine is available, report
container verification pending; ticket 02 cannot claim successful validation
until its checks run in an actual container. Use mocked providers for runtime
checks; do not make paid calls in this ticket.

## Scope

Packaging and its configuration only. Ticket 02 owns repeatable container checks
and CI; ticket 03 owns the complete Railway dashboard guide. No Railway resource
creation, account authentication, publishing, deployment, or website changes.

## Answer

Implemented production Docker packaging on `implement/railway-ticket-01`:
multi-stage Python 3.13.18/bookworm image, pinned uv 0.12.5, locked non-editable
web installation, runtime OpenMP support, one Uvicorn worker, runtime port,
persistent cache/ledger defaults, and preserved proxy/logging options.
Added build-context exclusions, a public environment example, expanded Git
environment-file exclusions, and [local Docker instructions](../../../docs/docker.md).
Existing application, RAG/CLI source, dependencies, and lockfile are unchanged.

Verification performed:

- `uv run --locked --extra web --extra dev --with psutil python -m pytest -q`:
  **132 passed**.
- A separate temporary production environment installed with
  `uv sync --locked --extra web --no-dev --no-editable --python 3.13`:
  **passed**, 25 installed distributions, local Python 3.13.7 on macOS.
- From outside the checkout, that installation imports FAISS and the API, finds
  byte-identical copies of all four bundled source documents, and is non-editable.
  It contains no pytest, Ruff, or Hatchling. Imports run without the OpenAI key,
  with outbound network operations blocked, and create no retriever/cache/logs.
- Startup shell syntax, documented environment defaults, Git environment-file
  exclusions, documentation links, and `git diff --check`: **passed**.

Linux image build/imports, runtime port/signal behavior inside a container, and
container cache-reuse checks remain **pending**. No Docker CLI/engine or existing
Docker/OrbStack installation is available on this workstation. The image-level
acceptance criterion remains unchecked. Packaging is resolved under this ticket's
explicit engine-unavailable verification allowance; ticket 02 must run actual
Linux container checks before claiming the image is verified. The local install
is supporting evidence, not a substitute for those checks. No paid requests,
Railway resources, publication, or deployment were performed.

## Comments

2026-10-30: Specified and queued; implementation not started.

2026-10-30: Claimed for implementation on `implement/railway-ticket-01` at the
user's request. Existing uncommitted specification and ticket files are retained
on this branch.

2026-10-30: Packaging implementation completed. Local checks pass; container
verification is explicitly deferred to ticket 02 as permitted above. Ticket 02
is unblocked for implementation; its actual container results remain pending.
