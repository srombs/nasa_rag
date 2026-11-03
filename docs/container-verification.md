# Linux container verification and CI

The **Tests and Linux container** workflow in
[checks.yml](../.github/workflows/checks.yml) runs on pull requests and pushes to
`main`. Its single job runs the mocked CLI/API/profiling regression suite and
builds/checks the root production Dockerfile. It uses `uv.lock` with the `web`,
`dev`, and `profile` extras, pinned uv, and the Dockerfile's Python version.
GitHub's Python setup action installs that interpreter explicitly; pinned uv
does not need to know how to download newer Python patch releases.
The optional `profile` extra supplies psutil for the existing profiling tests;
neither development nor profiling packages enter the production image.

The workflow uses no OpenAI or Railway secrets. It does not publish an image,
apply infrastructure, or deploy a service. It has read-only repository access.

## Repeat the checks

With a Docker CLI and running Linux Docker engine, from the repository root:

```sh
python3 scripts/check_container.py --output /tmp/nasa-rag-container-verification.json
```

The controller uses only Python's standard library. By default it builds the
production image as `nasa-rag:check`; `--image TAG` changes that tag.
Use `--skip-build --image TAG` only to check an already built image. The report
records its immutable image ID, architecture, and exact startup command.
The build needs registry/package access; the runtime checks disable container
networking and use an explicit dummy key only in the child server environment.
No host key, local cache, environment file, or checkout is copied into the image.

The check performs these steps:

1. Import the installed API/package and FAISS in the production image, find all
   four bundled documents, verify development/profiling dependencies are absent,
   and check that imports did not initialize a cache or cost ledger.
2. Create a uniquely named temporary Docker volume at `/data`. In a separate
   fixture process, generate synthetic 1,536-dimensional embeddings for the
   actual bundled corpus and create a compatible FAISS cache using the normal
   ingestion/retriever interfaces. Validate its text, shape, and index vectors.
3. Run two fresh containers sequentially against the same writable volume.
   A test controller launches the image's inspected production command unchanged
   as its child, with `PORT=8765`. Test scripts are mounted read-only at `/checks`;
   the runtime image and production startup command contain no test hook.
4. Enable a child-only Python startup hook that substitutes the OpenAI HTTP
   client using the existing profiling mock. It observes and gates the actual
   app lifespan for a readiness check, then calls its original initialization.
   Document-embedding requests fail immediately. The actual planning, retrieval,
   reranking, generation, citation checks, and request controls run unchanged.
5. Verify health fails before initialization and succeeds after it; check the
   supplied port binds on IPv4 wildcard and the server spawns no extra worker
   processes. Health must make zero model calls. Hold one question at the
   provider boundary, verify a second receives `503 busy`, and check health
   remains responsive without provider calls while the first is active.
6. Release the question and require the exact mock answer in the existing
   `{request_id, answer}` envelope, valid UUID/header correlation, and the full
   expected 13 provider calls. Observe graceful lifespan shutdown after SIGTERM.
   Compare embedding contents and the FAISS hash/mtime before and after each
   process. The existing loader rewrites embedding JSON, so only its contents
   must be unchanged. Both runs require zero startup/document-embedding calls.
7. Write the report and remove only the temporary containers and volume created
   by this check. The built image remains for inspection. Failed assertions,
   builds, imports, or missing Docker exit nonzero. After runtime verification
   begins, a partial report remains marked `pending` on failure.

The `container-verification` GitHub artifact contains the JSON report when one
was produced, including partial runtime results on failure. Build/import failures
can happen before a report exists; consult the failed step's logs in that case.

## Memory observations and limits

The runtime probe reuses the existing profiling sampler, cgroup discovery,
counter reads, and cache validation. On Linux it reads the server child's
`/proc/<pid>/status` RSS, so no psutil installation is required in the production
image. It samples startup, two seconds of loaded idle, health, a question, and
two seconds of idle after the question at 0.01-second intervals. Readiness and
shutdown snapshots also record the worker's OS lifetime RSS high-water marks.
The startup sample includes the deliberately gated readiness interval.

Readable cgroup v2 counters supply sampled `memory.current` means/peaks and
`memory.peak`. Container figures include the probe, server, and page cache;
process RSS excludes the probe. Lifetime peaks are never reset and cannot be
assigned to a single phase. Unavailable readings are null with a pending status,
not zero. Short spikes may fall between samples. Process RSS and cache file size
are not substitutes for container memory.

These are synthetic warm-cache checks. Both starts reuse a fixture; neither
measures empty-cache document embedding, real model latency/TLS/output sizes,
extended traffic, or Railway billing/capacity. The 1,536-dimensional shape is
representative of the current default embedding dimension, but identical mock
vectors do not benchmark retrieval quality. Deployed observations remain separate.

## Railway handoff for ticket 03

After this workflow is published, obtain a successful **Tests and Linux container**
run for the deployed source commit. In the Railway service's source settings,
confirm the GitHub source branch is `main`, accept any pending Railway GitHub App
permission update, and enable **Wait for CI**. Railway requires a workflow with
a push trigger on that branch; PR-only checks do not satisfy this prerequisite.
The service's `/health` readiness check remains a separate runtime requirement.

Railway waits for GitHub Actions workflow runs on the commit, not a manually
selected job name. A failed workflow skips deployment. Skipped/neutral workflows
do not block; cancellation has special handling if another workflow succeeded.
This workflow has no path filters or cancellation group that would bypass the
checks on `main`. See [Railway's Wait for CI requirements and behavior](https://docs.railway.com/deployments/github-autodeploys#wait-for-ci).

This ticket documents the prerequisite. Confirming the dashboard toggle and
observing a failed check prevent a hosted deployment belong to ticket 04.
The user's existing deployment has not been inspected or modified by these checks.

## Recorded verification

Local Docker execution is **pending**: this workstation has no Docker CLI or
engine. The controller exits nonzero with `No such file or directory: 'docker'`;
that is an unavailable check, not a passed container test. A local subprocess
trial and the existing regression tests provide supporting evidence only.
GitHub-hosted workflow execution and Linux/container measurements are **pending**
until the branch is published and a Linux runner executes the workflow.

Executed on the workstation during implementation:

- `uv sync --locked --extra web --extra dev --extra profile`: passed.
- `uv run --no-sync python -m pytest -q tests/test_web_runtime.py`: **3 passed**.
- `uv run --no-sync python -m pytest -q`: **132 passed**.
- `uv run --no-sync ruff check scripts tests/test_web_runtime.py`: passed.
- `uv run --no-sync mypy --follow-imports=silent --ignore-missing-imports --check-untyped-defs scripts`:
  passed, including a separate `--platform linux` typecheck.
- `git diff --check`: passed.
- Local trial of the fixture/probe CLI, using two fresh child processes and the
  Dockerfile's exact `CMD` against the same temporary cache: passed. Both starts
  reused cache, made zero startup/health/document-embedding requests, and made
  the expected 13 mocked provider calls for one successful question. The busy
  request, UUID/header, exact answer, and graceful shutdown checks passed.
  This trial used macOS; `/proc` listener/worker checks and container accounting
  remain Linux-only. Its temporary fixtures/reports were removed after the trial.
