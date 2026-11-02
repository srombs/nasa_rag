# Railway deployment specification

Recorded 2026-10-29; ticket breakdown added 2026-10-30. This document and the
[implementation tickets](README.md) specify future packaging and deployment
work. Creating these planning artifacts does not authorize implementation or
deployment.

## Goal and agreed decisions

Package the existing NASA RAG FastAPI service for Railway using a repository-owned
Dockerfile. The user will connect and configure the service through Railway's
website; account setup and deployment are separate from preparing the package.

- Use Docker packaging rather than Railway's automatic Python builder.
- Connect `srombs/nasa_rag` through Railway's GitHub integration, with automatic
  deployments from the selected branch.
- Attach persistent storage for document embeddings and the search-index cache.
- Keep the backend private until portfolio integration is implemented.
- Leave the website UI and proxy integration for a separate session.
- The source repository and NASA documents are public. Commit deployment
  configuration and documentation normally; runtime credentials remain external.
  Public source availability does not change the agreed initial backend access.

The existing [FastAPI service plan](../../docs/fastapi-service-plan.md) and
[API runtime contract](../../docs/web-api.md) remain the source of truth for
application behavior. Preserve the current RAG pipeline and CLI.

## Docker packaging requirements

1. Add a root `Dockerfile` that installs the existing package with its `web`
   extra and locked dependencies from `uv.lock`. Pin the Python base-image
   version and any build-tool version used. Exclude development dependencies
   from the runtime image; avoid requiring a compiler in the runtime image.
2. Include the four bundled NASA documents in the installed application. Verify
   that the Linux image can import FAISS and locate the documents; install any
   required system libraries explicitly.
3. Add `.dockerignore` to exclude credentials and local state, including `.env`
   files, `.git`, virtual environments, generated caches, logs, and bytecode.
   Do not copy local embeddings or credentials into image layers.
4. Launch `nasa_rag.web:app` with exactly one Uvicorn worker, listening on
   Railway's runtime `PORT` and a non-loopback address. Ensure the listener works
   with the target Railway environment's private-network address family and
   readiness checks. Preserve `--no-proxy-headers` and `--no-access-log`; forward
   shutdown signals to the server process.
5. Supply `OPENAI_API_KEY` only through runtime environment configuration. Keep
   the existing configurable response deadline and trusted-proxy behavior.
   Leave proxy trust empty until the actual website proxy is configured.
6. Use a writable persistent volume mounted at `/data`, with
   `NASA_RAG_CACHE_DIR=/data/cache` and
   `NASA_RAG_COST_LOG_PATH=/data/logs/model_costs.jsonl`. Create directories at
   runtime as needed. Reuse compatible embeddings and index files after restart.
7. Image builds must not initialize the retriever or make model requests.
   An empty runtime volume can trigger paid document-embedding calls during
   startup; document this separately from warm-cache startup and health checks.
8. Document the Railway settings below and use the supported configuration
   mechanism if keeping them in code. Do not add orchestration services or
   databases solely for packaging.

## Railway configuration and supporting files

### Dashboard settings for the first deployment

| Setting | Required behavior |
| --- | --- |
| Source | `srombs/nasa_rag`, repository root, `main` branch, GitHub autodeploy enabled. |
| Build/start | Detect the root Dockerfile and use its startup command. Avoid a second conflicting dashboard start command. |
| Readiness | Check `/health` with an initial 300-second startup allowance. It must wait for retriever initialization. This is deployment readiness, not continuous uptime monitoring. |
| Recovery | Restart on process failure, with at most three crash-restart attempts. Keep this separate from model-request retries. |
| Scale | One replica in one region and one Uvicorn worker, preserving the existing admission controls. |
| Storage | Attach the persistent `/data` volume before the first runtime start; verify the process can write its cache and ledger. |
| Network | Keep public domains and TCP proxies absent initially. Verify private connectivity uses the listener's supported address family. |
| Capacity | Select CPU/memory limits using Linux/container measurements and startup/request peak headroom; local macOS RSS is provisional evidence. |
| Hosting lifecycle | Document the chosen region and sleep/always-on setting during dashboard setup. Docker packaging does not decide these. |

The operator supplies the runtime key in Railway's Variables tab. Record safe
defaults for port, cache path, cost-log path, response deadline, and proxy trust
in the repository. Persistent storage is attached at runtime, not during image
build or a pre-deploy command.

### Configuration format

Checked 2026-10-29: Railway documents `railway.toml` / `railway.json` as deprecated,
with no opt-in for new services and a 2026-12-01 cutoff for existing users. Do not
introduce either legacy file for this new deployment. See
[the current configuration notice](https://docs.railway.com/config-as-code).

The dashboard procedure is the initial delivery path. Optionally capture the
service settings in `.railway/railway.ts`, Railway's supported TypeScript
infrastructure-as-code format, with pinned development tooling. Its supported
resources include GitHub sources, readiness, replicas, environment defaults,
and volume mounts. Keep credential values external. This file requires a
separate plan/apply step; GitHub application autodeploy does not apply it.
Do not introduce automatic infrastructure changes in this workstream. See
[the IaC workflow](https://docs.railway.com/infrastructure-as-code) and
[authoring reference](https://docs.railway.com/infrastructure-as-code/reference).

### Additional repository artifacts

- Add a root `.env.example` with an empty `OPENAI_API_KEY` and documented safe
  defaults for the existing runtime variables. Ensure real `.env` files remain
  ignored by Git and excluded from Docker build context. The example is public
  documentation, not a production secret file or an automatic credential loader.
- Add a small GitHub Actions workflow that runs the existing mocked web/CLI tests
  and builds the Linux Docker image without credentials. Include a container
  import/bundled-data check without starting the real pipeline. Use locked
  dependencies and run on pull requests and pushes to `main`. No Railway token
  or live OpenAI key is needed for these checks.
- Once that workflow exists, document enabling Railway's **Wait for CI** setting
  so failed checks prevent application autodeploys. CI verifies the build; the
  runtime health check separately verifies service initialization.
- Add the deployment guide with dashboard steps, first-start embedding behavior,
  private health checks, volume-reuse verification, and how to redeploy a known
  good source revision without deleting the persistent cache. Document the brief
  downtime possible when redeploying a service with a volume.

The handoff should also point to Railway's compute alert/usage-limit controls,
explaining that a hard limit can stop other workloads in the same workspace.
Do not select a spending amount in this spec or treat Railway compute limits as
a cap on this application's external OpenAI usage.

## Operator handoff

Document how to build and run the image locally and how to configure the GitHub
source, runtime secret, persistent volume, health check, and private networking
in Railway's dashboard. Railway builds the Dockerfile from GitHub; Docker is
needed locally only for local container verification.

The initial service must have no public domain or TCP proxy. Explain that a
Dockerfile does not enforce network privacy: those settings belong to Railway.
Private service addresses are available only within the same Railway project
environment; the portfolio will later need a suitable server proxy or a
separately designed authenticated public connection.

## Acceptance and verification

- The production image builds from a clean checkout with locked web dependencies
  and bundled documents, without a local virtual environment, cache, or API key.
- The installed application and FAISS import successfully in the Linux image.
- The container honors a supplied port, starts one worker, and becomes healthy
  only after retriever initialization. Health requests make no model calls.
- Repeatable container checks using mocked provider calls verify question
  handling and compatible cache reuse across restarts with the same volume.
  Do not commit test embeddings as production cache data or bake mock-provider
  behavior into the production startup command.
- Existing API and CLI behavior, request controls, and safe logging remain
  unchanged; relevant existing tests pass.
- The example environment file contains no credentials, the dashboard checklist
  covers every required setting, and CI requires no deployment/provider secrets.
- A failed CI run blocks deployment when Wait for CI is enabled. Packaging docs
  distinguish Docker builds, application autodeploys, and optional IaC applies.
- Record the build and smoke-check commands and their results. If a Docker
  engine is unavailable, mark container verification pending rather than treating
  a local Python test run as proof that the image works.

Actual Railway provisioning, account authentication, publishing, live model
requests, deployed memory measurements, and website changes are outside this
specification update. Hosting sleep settings and budget limits are not settled
by the Docker choice. Do not reopen resolved API tickets to implement packaging.

## References

- [Railway Dockerfile builds](https://docs.railway.com/builds/dockerfiles)
- [Railway configuration deprecation notice](https://docs.railway.com/config-as-code)
- [Railway infrastructure as code](https://docs.railway.com/infrastructure-as-code)
- [Railway IaC authoring reference](https://docs.railway.com/infrastructure-as-code/reference)
- [Railway persistent volumes](https://docs.railway.com/volumes)
- [Railway private domains](https://docs.railway.com/networking/domains/working-with-domains)
- [Railway GitHub autodeploys and Wait for CI](https://docs.railway.com/deployments/github-autodeploys)
- [Railway runtime variables](https://docs.railway.com/variables)
- [Railway compute usage controls](https://docs.railway.com/pricing/cost-control)
- [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
