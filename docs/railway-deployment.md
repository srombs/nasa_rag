# Deploy the private API through Railway's dashboard

Use this guide for [ticket 04](../.scratch/railway-deployment/issues/04-deploy-through-dashboard.md),
including an audit of the deployment the user reports already exists. The guide
was checked against official Railway documentation on **2026-11-03**. Dashboard
configuration and hosted verification have not been performed by this workstream.

## Start from a tested revision

Use `srombs/nasa_rag`, branch `main`, with the repository root as the source
directory. This guide must be merged and available on GitHub before the handoff
is complete. In GitHub Actions, find a successful **Tests and Linux container**
run for the exact `main` commit you intend to deploy; record its SHA and run URL.
Do not use a passing check for a different commit as that evidence.

Ticket 02's [recorded Linux run](container-verification.md#recorded-verification)
passed the production image build, imports, four bundled documents, mocked HTTP
contract, readiness, concurrency, and two-process cache reuse. It used synthetic
embeddings and mocked providers. It did not verify the existing Railway service,
a real answer, or the deployed revision's memory requirements.

For local verification with Docker, from the repository root:

```sh
python3 scripts/check_container.py --output /tmp/nasa-rag-container-verification.json
```

This builds the actual production image and runs network-disabled runtime checks
with temporary test fixtures. No key is needed. See [container verification](container-verification.md)
for details and [the Docker guide](docker.md) for separate build/import commands,
the live local launch, and a loopback-only health check. Docker is needed locally
only for these local checks; Railway builds from GitHub itself.

## What configures the service

| Repository artifact | How it is used |
| --- | --- |
| Root `Dockerfile`, `.dockerignore` | Railway detects the Dockerfile; Docker applies build-context exclusions. The image installs locked web dependencies and supplies the one-worker startup command. |
| `pyproject.toml`, `uv.lock`, `src/`, `data/` | Inputs to the Docker build, including the four bundled NASA documents. |
| `.github/workflows/checks.yml` | GitHub runs the **Tests and Linux container** workflow on pull requests and pushes to `main`. It does not deploy. |
| `.env.example` | Public variable reference. Railway may suggest importing its values; inspect and save them in Variables. The application does not load this file. |
| Markdown in `docs/` and `.scratch/` | Instructions and specifications; Railway does not apply them as runtime settings. |

Source selection, CI gating, readiness, restart policy, scaling, storage,
networking, resources, and runtime secrets are saved in the dashboard below.
[Dockerfile detection](https://docs.railway.com/builds/dockerfiles) is automatic.
[Suggested variables](https://docs.railway.com/variables#suggested-variables)
still require the operator to choose/import their values.

Do not add `railway.toml` or `railway.json` for this setup: Railway's current
[configuration notice](https://docs.railway.com/config-as-code) deprecates them,
disallows new-service opt-in, and ends existing support on 2026-12-01. Optional
future capture in `.railway/railway.ts` uses the separate
[infrastructure-as-code plan/apply workflow](https://docs.railway.com/infrastructure-as-code).
It requires explicit infrastructure review and apply; ordinary GitHub application
autodeploy does not apply it. This repository supplies no IaC file or automation.

## Configure or audit the dashboard

For an existing service, record its current project, environment, service, source
revision, and volume identity before editing. Retain its stored data. For a new
service, create an empty service in the chosen environment so you can stage the
settings and volume before connecting a deployable source and starting it.
Use **New → Empty Service**, then **Settings → Service Source → Connect Repo**
when ready; see [service creation and sources](https://docs.railway.com/services).
Connecting GitHub can trigger a deployment; an empty cache will incur paid
embedding calls once a valid key is supplied. Review the staged changes before
deploying them.

Configure these service settings (labels may move within Settings):

| Area | Value or action |
| --- | --- |
| Source | Connect GitHub repository `srombs/nasa_rag`; authorize the Railway GitHub App for it. Select `main` and root `/` (no subdirectory). Enable GitHub autodeploys. |
| Build | Use the root, capitalized `Dockerfile`; confirm Dockerfile detection in build logs. Remove conflicting build overrides or custom Dockerfile-path variables. |
| Start | Leave the custom Start Command unset so the image's `CMD` runs. Leave Pre-deploy Command empty; cache initialization belongs to runtime. |
| Readiness | Healthcheck Path `/health`, Healthcheck Timeout **300 seconds** initially. The container uses runtime `PORT`; `/health` becomes available after retriever initialization. |
| Restart | **On Failure**, maximum **3** retries. Set this explicitly; the platform default allows more. This policy concerns process crashes, independently of provider-request retries. |
| Scale | **One replica in one region**. The image supplies exactly **one Uvicorn worker**; do not override it. |
| Volume | Attach a persistent volume to this service at **`/data`** before the first runtime start. Keep that same volume across redeploys. |
| Networking | Keep generated/custom public domains and TCP proxies absent. Audit and remove any existing public exposure as part of the private-service setup. Retain its private domain. |
| Lifecycle and limits | Choose and record region, CPU/memory limits, Serverless on/off, and compute usage controls as described below. |

Railway [inherits the Dockerfile command](https://docs.railway.com/deployments/start-command#dockerfiles--images)
when no custom command is set. The image's startup command is:

```sh
exec uvicorn nasa_rag.web:app --host 0.0.0.0 --port "$PORT" \
  --workers 1 --no-proxy-headers --no-access-log
```

Use an environment with IPv4 private networking. The image listens on IPv4
`0.0.0.0`; Railway documents dual IPv4/IPv6 private DNS for environments created
after October 16, 2025, while legacy environments may resolve only IPv6. Verify
the existing environment rather than assuming its age. If it is IPv6-only,
pause the rollout and plan a compatible environment or listener change; this
guide does not change the application. See [private domains](https://docs.railway.com/networking/domains/working-with-domains#private-domains).

[Readiness checks](https://docs.railway.com/deployments/healthchecks) run during
deployment, not as ongoing uptime monitoring. A 300-second initial allowance is
separate from the API's 120-second response deadline. If initialization exceeds
it, investigate logs, provider access, and resources before adjusting the timeout.
[Restart policy](https://docs.railway.com/deployments/restart-policy) handles
process failure; it does not restart an otherwise running process for every
failed health request.

### Runtime variables and persistent storage

In the service's **Variables** tab, add `OPENAI_API_KEY` using **New Variable**.
Enter its value only there; do not commit it, put it in a build argument, print
the environment, or paste it into the verification record. Review and deploy
staged variable changes. See [service variables](https://docs.railway.com/variables#service-variables).

| Variable | Runtime setting |
| --- | --- |
| `OPENAI_API_KEY` | Required secret supplied by the operator. |
| `PORT` | Use Railway's runtime value; the image falls back to `8000`. If setting it explicitly, `8000` is consistent with the image and health check. |
| `NASA_RAG_CACHE_DIR` | `/data/cache` |
| `NASA_RAG_COST_LOG_PATH` | `/data/logs/model_costs.jsonl` |
| `NASA_RAG_RESPONSE_TIMEOUT_SECONDS` | `120` |
| `NASA_RAG_TRUSTED_PROXIES` | Empty until the actual server proxy is configured. |

The Dockerfile already supplies the non-secret defaults. Save them explicitly in
Variables if desired and inspect any existing overrides. Do not import an empty
key from `.env.example` over the real secret.

**First startup on an empty or incompatible cache makes paid document-embedding
requests.** The image build makes no model requests and contains no production
cache. Compatible embeddings and the FAISS index are reused on restart; changing
documents, embedding settings, or cache compatibility may require new work.
Ordinary `/health` requests make no model calls. A live `/ask` runs the paid full
pipeline and needs separate authorization during ticket 04.

The app creates its cache directory at startup and the ledger's parent on write.
The current image runs as root, matching Railway's default volume ownership.
Verify both paths are writable; if changing container users later, arrange
ownership/permissions before starting the app. [Volumes](https://docs.railway.com/volumes)
are mounted only at runtime, not during builds or pre-deploy commands. Do not
move initialization into either phase or copy test fixture embeddings to `/data`.

### Wait for CI

In the service's source settings, enable **Wait for CI**. Accept any pending
Railway GitHub App permission update. The repository's
[workflow](../.github/workflows/checks.yml) is named **Tests and Linux container**
and has a push trigger on `main`, as Railway requires; PR-only checks are
insufficient. Keep autodeploy enabled and record the exact deployed SHA/run URL.

Railway evaluates workflow runs on the commit rather than a selected job name.
Failed workflows skip deployment; skipped/neutral runs do not block, and cancelled
runs have conditional handling when another workflow passes. Consult the
[current Wait for CI behavior](https://docs.railway.com/deployments/github-autodeploys#wait-for-ci).
The runtime `/health` check is a separate gate. Record the toggle and observed
gate behavior in ticket 04; if a failed-run blocking case has not been exercised,
leave that observation pending. Manual recovery actions require their own review
of the chosen revision and configuration.

### Capacity, region, sleep, and budget choices

Ticket 02's [Linux measurements and raw report](container-verification.md#memory-observations-and-limits)
show roughly **197 MiB worker idle RSS**, **212 MiB worker question peak**,
**261 MiB container loaded idle**, and **276 MiB container question peak**.
Container values include the test probe and page cache. They represent two short
synthetic warm-cache runs, not empty-cache ingestion, real provider traffic,
sustained load, Railway billing, or a measured production minimum.

Choose a memory limit with headroom above that container peak; a 256 MiB cap is
already below the observed mock peak. A **512 MiB initial trial** is an operator
option, not a proven capacity requirement. Record the chosen CPU/memory limits,
observe Railway startup and loaded idle memory, and adjust for actual peaks or
OOM exits. A live question peak remains pending unless separately authorized.
Do not substitute cache file sizes or macOS RSS for container capacity.

Choose one available region and record it. Keep a future same-environment server
proxy's location in mind. A volume follows its service's region; later region
moves require migration and downtime. See [regions](https://docs.railway.com/deployments/regions).

Choose **Serverless** on for sleeping when inactive or off for always-on behavior;
this choice is not settled by the Dockerfile. Sleep reduces idle running time but
adds wake/startup delay, and an initial wake request can fail. Record the setting
and deploy for it to take effect. See [Serverless](https://docs.railway.com/deployments/serverless).

In **Workspace Usage → Set Usage Limits**, select the intended workspace and set
the operator's **Compute Usage** email alert and optional hard limit. No amount
has been agreed. A hard limit can take other workloads in that workspace offline.
Railway compute controls (and its separate Agent Usage controls) do not cap this
app's external OpenAI charges. See [cost control](https://docs.railway.com/pricing/cost-control).

## Verify privately, then restart against the same volume

After applying the reviewed configuration, watch build and deployment logs for
Dockerfile selection, successful initialization, and readiness. Keep public
domains/TCP proxies absent throughout these checks.

For a shell **inside the deployed container**, use the dashboard's service
command palette to **Copy Service Instance ID**, then connect using a registered
Railway SSH key:

```sh
ssh <service-instance-id>@ssh.railway.com
```

Replace the placeholder before running. This is the service **instance** ID, not
the service ID. The authenticated [Railway SSH procedure](https://docs.railway.com/cli/ssh)
also supports `railway ssh` after selecting the intended project, environment,
and service. It needs no public domain/TCP proxy. A local `railway shell` only
supplies variables; use an actual remote container session for these commands.

Inside that session, use Python already in the image (curl is not installed):

```sh
python - <<'PY'
import json
import os
import urllib.request

url = "http://127.0.0.1:" + os.environ.get("PORT", "8000") + "/health"
with urllib.request.urlopen(url, timeout=10) as response:
    assert response.status == 200
    assert json.load(response) == {"status": "ok"}
print("Private in-container health: OK")
PY
```

The following snapshot prints only file metadata, hashes, and operation counts.
Run it after initial readiness, again after several health checks, and again
after restarting and reaching readiness on the **same attached volume**:

```sh
python - <<'PY'
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

cache = Path(os.environ["NASA_RAG_CACHE_DIR"])
ledger = Path(os.environ["NASA_RAG_COST_LOG_PATH"])
for directory in (cache, ledger.parent):
    assert directory.is_dir() and os.access(directory, os.W_OK), directory
for relative in ("embeds/document_cache_100_20.json", "faiss/document_100_20.index"):
    path = cache / relative
    data = path.read_bytes()
    if path.suffix == ".json":
        data = json.dumps(json.loads(data), sort_keys=True).encode()
    print(relative, "bytes=", path.stat().st_size,
          "sha256=", hashlib.sha256(data).hexdigest())
counts = Counter()
if ledger.exists():
    for line in ledger.read_text().splitlines():
        counts[json.loads(line)["operation"]] += 1
print("recorded_model_operations=", dict(counts))
PY
```

Save each output with its deployment SHA/ID and observation time. Health-only
intervals must add no ledger operations. A warm restart must add no
`document_embedding` entries and must retain embedding content and FAISS hashes.
Embedding JSON may be rewritten by the loader, so mtime alone does not prove
cache misses; the snippet hashes its parsed content. Check that the same volume
identity/mount and runtime paths are retained. If the ledger is missing or
unwritable, absence of records does not prove zero provider calls; investigate
before marking reuse verified. The snapshot deliberately fails for missing cache
files. It does not load the retriever or make requests.

Restart from the deployment's menu, wait for readiness, reconnect to the new
container session, and repeat the commands. If necessary, redeploy that same
tested revision to verify persistence across container replacement as well.
Do not delete/wipe the volume or run a second server against it.

Railway's [volume constraints](https://docs.railway.com/volumes/reference) permit
brief redeployment downtime even with a health check, because deployments cannot
mount the same volume concurrently. Schedule the restart accordingly.

The private name `<service-name>.railway.internal` is reachable only within the
same Railway project **and environment**, not from a visitor's browser or an
unrelated hosting environment. Later portfolio integration needs a suitable
server-side proxy in that network or a separately designed authenticated access
path. A public GitHub repository does not automatically expose this service.
See [private networking](https://docs.railway.com/networking/private-networking).

## Logs and recovery

Use the deployment's Build/Deploy Logs or the environment's Observability view;
see [Railway logs](https://docs.railway.com/observability/logs). Normal web request
logs contain request IDs, status, and elapsed time. The usage ledger records model
operation/usage estimates without prompts or answers. Preserve the image's
`--no-access-log` and `--no-proxy-headers`, keep proxy trust empty, and do not
enable prompt/provider debug logs or dump secrets into a support record.

On a failed build, fix or select a tested source revision. On failed startup,
check the key's presence without printing it, `/data` attachment/permissions,
provider access, `PORT`, timeout, and Railway memory/OOM observations. After three
crash retries the configured policy stops retrying; fix the cause before restart.

To recover, choose a known good deployment in **Service → Deployments → … →
Rollback**, subject to the plan's image retention. **Redeploy** on a selected
historical deployment uses its code/configuration; **Deploy Latest Commit** uses
the connected branch's latest commit and is not a rollback. Railway restores
variables with a rollback, so inspect the restored configuration, key validity,
volume attachment/paths, and readiness before relying on it. Preserve `/data`:
code rollback does not undo volume contents. If cache formats are incompatible,
preserve a backup and plan recovery rather than wiping data. Recheck health and
cache reuse afterward. See [deployment actions](https://docs.railway.com/deployments/deployment-actions).

## Ticket 04 operator record

Append results to [ticket 04](../.scratch/railway-deployment/issues/04-deploy-through-dashboard.md)
without credential values. Keep unobserved items pending:

- [ ] Exact deployed GitHub SHA, successful matching `main` CI run URL, and deployment ID/result.
- [ ] Project/environment/service identity; IPv4 private networking; public domains and TCP proxies absent.
- [ ] GitHub source/root/branch/autodeploy, detected Dockerfile, inherited start command, one replica/worker/region.
- [ ] Runtime variable names/paths, `/data` volume identity, writable cache and ledger, `/health`, 300-second allowance, On Failure with three retries.
- [ ] Chosen region, CPU/memory limits/headroom, Serverless setting, and compute alert/hard-limit decision.
- [ ] First-start embedding usage understood; private health succeeds without new ledger operations.
- [ ] Same-volume restart/replacement observations and snapshots demonstrate compatible cache reuse.
- [ ] Hosted startup duration and memory compared with the provisional Linux evidence; any resource adjustments recorded.
- [ ] Wait for CI enabled; failed-workflow blocking observed or explicitly pending.
- [ ] Live-provider answer/latency/peak measurements authorized and recorded, or explicitly pending. Portfolio/proxy integration remains future work.
