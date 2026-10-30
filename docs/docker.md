# Run the API in Docker

The root Dockerfile packages the existing FastAPI adapter with its `web` extra
and dependencies from `uv.lock`. It pins Python to `3.13.18-slim-bookworm` and the
uv build tool to `0.12.5`. The final image contains the installed application,
its Python dependencies, the four NASA documents, and the Linux OpenMP library
needed by FAISS. It omits uv, application source-checkout metadata, development
dependencies, and local caches. Keep the pinned versions updated when deliberately
upgrading the runtime.

## Build and inspect without model requests

From the repository root, with Docker installed and its engine running:

```sh
docker build --tag nasa-rag:local .
```

The build needs access to image/package registries but no OpenAI key. It installs
the package without initializing the retriever or requesting embeddings.

Check installed imports and the bundled corpus without starting the API or
allowing container network access:

```sh
docker run --rm --network none --entrypoint python nasa-rag:local -c \
  'import faiss; import nasa_rag.web; from nasa_rag.paths import data_directory; sources = sorted(p.name for p in data_directory().glob("*.txt")); assert sources == ["hubble.txt", "iss.txt", "nasa_overview.txt", "space_shuttle.txt"]; print("FAISS, API import, and bundled documents: OK")'
```

This check makes no model calls. Repeatable mocked runtime and CI checks are
tracked separately in deployment ticket 02.

## Run with a persistent cache

Supply `OPENAI_API_KEY` in your shell environment, then run:

```sh
docker volume create nasa-rag-data
docker run --rm --name nasa-rag \
  --publish 127.0.0.1:8000:8000 \
  --mount type=volume,source=nasa-rag-data,target=/data \
  --env OPENAI_API_KEY \
  nasa-rag:local
```

**An empty cache makes paid document-embedding requests during startup.** Starting
the API requires a valid runtime key and network access to OpenAI. Failed
initialization stops startup. A compatible cache on the same volume is reused
after restart. Stop the container before starting another against that cache;
the API is designed for one worker and one replica.

The API creates its cache directory when it starts and the usage logger creates
its parent directory when writing. The image runs with the default root user,
which can write to a default Docker/Railway volume. If changing users or using a
bind mount, ensure the configured cache and log directories remain writable.

In a second terminal, once startup completes:

```sh
curl --fail http://127.0.0.1:8000/health
```

Expect `{"status":"ok"}`. A health request makes no model calls. Submitting a
question to `/ask` runs the existing paid pipeline; see [the API guide](web-api.md)
for its request format and behavior.

Use `docker stop nasa-rag` to stop the server. The container is removed by
`--rm`; the named volume remains for the next start. The shell startup command
uses `exec` so the server receives shutdown signals. Allow sufficient stop grace
time for an active pipeline request if graceful completion is needed.

## Environment and port configuration

| Variable | Container default |
| --- | --- |
| `OPENAI_API_KEY` | Required at runtime; no value in the image |
| `PORT` | `8000` |
| `NASA_RAG_CACHE_DIR` | `/data/cache` |
| `NASA_RAG_COST_LOG_PATH` | `/data/logs/model_costs.jsonl` |
| `NASA_RAG_RESPONSE_TIMEOUT_SECONDS` | `120` |
| `NASA_RAG_TRUSTED_PROXIES` | empty |

Alternatively, copy `.env.example` to a local `.env`, fill in your runtime key,
and replace `--env OPENAI_API_KEY` with `--env-file .env` in the run command.
Docker reads that file; the Python application does not load it automatically.
Real environment files are ignored by Git and excluded from the build context.
The example's `/data` paths are container paths, not local checkout defaults.

To use port `8080`, stop the current container and run:

```sh
docker run --rm --name nasa-rag \
  --publish 127.0.0.1:8080:8080 \
  --env PORT=8080 \
  --mount type=volume,source=nasa-rag-data,target=/data \
  --env OPENAI_API_KEY \
  nasa-rag:local
```

Then check `http://127.0.0.1:8080/health`. `EXPOSE 8000` is descriptive metadata;
the server uses the runtime `PORT` value. The image always runs one Uvicorn worker
with proxy-header handling and access logs disabled, as the API adapter requires.

## Railway compatibility

The container listens on IPv4 `0.0.0.0`. Use a new Railway environment with IPv4
private networking. Railway documents IPv4 and IPv6 private DNS for environments
created after October 16, 2025; legacy environments can be IPv6-only and require
a different listener configuration. See [Railway private domains](https://docs.railway.com/networking/domains/working-with-domains).

Mount a persistent volume at `/data` and set the runtime key in Railway's Variables
UI. Runtime mounts are not available during image builds. Keep public domains and
TCP proxies absent until website integration is designed; listening on a
non-loopback address inside the container does not itself publish a public URL.
Detailed dashboard setup and hosted verification belong to tickets 03 and 04.

## References

- [Official Python image tags](https://github.com/docker-library/official-images/blob/master/library/python)
- [uv non-editable Docker installations](https://docs.astral.sh/uv/guides/integration/docker/#non-editable-installs)
- [Railway Dockerfile builds](https://docs.railway.com/builds/dockerfiles)
