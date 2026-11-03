"""Private container probe: run the inspected production command, fully offline."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from profile_web_runtime import (
    DOCUMENT_CACHE,
    INDEX_CACHE,
    QUESTION,
    cgroup_directory,
    measure,
    validate_cache,
)

EXPECTED_ANSWER = "Mock answer: this run measures memory, not answer quality."
EXPECTED_REQUESTS = {
    "retrieval_plan": 1,
    "query_embedding": 1,
    "rerank_result": 10,
    "answer": 1,
}


def seed(cache: Path) -> dict:
    """Build isolated synthetic fixtures through the normal cache interfaces."""
    from nasa_rag.ingestion.chunkers import chunk_text
    from nasa_rag.ingestion.file_loader import save_document_cache
    from nasa_rag.models import DocumentChunk
    from nasa_rag.paths import data_directory
    from nasa_rag.retrieval.retriever import Retriever

    if cache.exists():
        raise RuntimeError("Fixture seeding requires a new, empty volume")
    documents = {
        source.name: [
            DocumentChunk(source.name, i, text, [1.0] + [0.0] * 1535)
            for i, text in enumerate(chunk_text(source.read_text(), 100, 20))
        ]
        for source in sorted(data_directory().glob("*.txt"))
    }
    save_document_cache(cache / DOCUMENT_CACHE, documents)
    Retriever(data_directory(), cache_directory=cache).load()
    metadata = validate_cache(cache)
    metadata["embedding_provenance"] = (
        "synthetic fixture; identical 1536-dimensional vectors"
    )
    return metadata


def run(cache: Path, command: list[str]) -> dict:
    before = validate_cache(cache)
    if before["dimensions"] != 1536:
        raise RuntimeError("Container fixture must use 1536 dimensions")
    port = int(os.environ["PORT"])
    opener = build_opener(ProxyHandler({}))

    def request(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        query = Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = opener.open(query, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response), response.headers

    with TemporaryDirectory(prefix="nasa-rag-container-") as temporary:
        directory = Path(temporary)
        environment = {
            **os.environ,
            "OPENAI_API_KEY": "offline-container-placeholder",
            "NASA_RAG_CONTAINER_CHECK_DIR": str(directory),
            "PYTHONPATH": os.pathsep.join(
                [
                    str(Path(__file__).with_name("container_site")),
                    str(Path(__file__).parent),
                ]
            ),
        }
        with (directory / "server.log").open("w+") as log:
            process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)

            def wait_for(predicate):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Production command exited during checks")
                    if predicate():
                        return
                    time.sleep(0.01)
                raise RuntimeError("Container runtime check timed out")

            def counts():
                return json.loads((directory / "provider.json").read_text())

            def ready():
                try:
                    status, body, _ = request("/health")
                    return status == 200 and body == {"status": "ok"}
                except (URLError, TimeoutError, ConnectionError):
                    return False

            def startup():
                wait_for(lambda: (directory / "startup.entered").exists())
                if ready():
                    raise RuntimeError("Health succeeded before initialization")
                (directory / "startup.release").touch()
                wait_for(ready)
                if not (directory / "ready.json").exists() or counts():
                    raise RuntimeError("Startup did not reuse the offline cache")
                if sys.platform == "linux":
                    children = Path(
                        f"/proc/{process.pid}/task/{process.pid}/children"
                    ).read_text()
                    if children.strip():
                        raise RuntimeError("Production server spawned extra workers")
                    listener = f"00000000:{port:04X}"
                    if not any(
                        row.split()[1] == listener and row.split()[3] == "0A"
                        for row in Path("/proc/net/tcp").read_text().splitlines()[1:]
                    ):
                        raise RuntimeError(
                            "Production listener did not bind the supplied port"
                        )

            def health():
                original = counts()
                for _ in range(3):
                    status, body, _ = request("/health")
                    if (status, body) != (200, {"status": "ok"}):
                        raise RuntimeError("Health contract failed")
                if counts() != original:
                    raise RuntimeError("Health made a provider request")

            def question():
                with ThreadPoolExecutor(1) as pool:
                    answer = pool.submit(request, "/ask", {"question": QUESTION})
                    try:
                        wait_for(lambda: counts().get("retrieval_plan") == 1)
                        status, body, headers = request("/ask", {"question": "Busy?"})
                        UUID(body["request_id"])
                        if (
                            status != 503
                            or body["error"]["code"] != "busy"
                            or headers["x-request-id"] != body["request_id"]
                        ):
                            raise RuntimeError("Concurrent question was not rejected")
                        health()
                        if counts() != {"retrieval_plan": 1}:
                            raise RuntimeError(
                                "Concurrent request reached the pipeline"
                            )
                    finally:
                        (directory / "question.release").touch()
                    status, body, headers = answer.result(timeout=30)
                UUID(body["request_id"])
                if (
                    status != 200
                    or set(body) != {"request_id", "answer"}
                    or body["answer"] != EXPECTED_ANSWER
                    or headers["x-request-id"] != body["request_id"]
                    or counts() != EXPECTED_REQUESTS
                ):
                    raise RuntimeError("Successful answer/pipeline contract changed")

            memory = {}
            cgroup = cgroup_directory(process.pid)
            try:
                for name, action in (
                    ("startup", startup),
                    ("loaded_idle", lambda: time.sleep(2)),
                    ("health", health),
                    ("question", question),
                    ("post_question_idle", lambda: time.sleep(2)),
                ):
                    _, memory[name] = measure(process.pid, action, 0.01, cgroup)
                health()
                if counts() != EXPECTED_REQUESTS:
                    raise RuntimeError("Unexpected provider calls after the question")
            except BaseException:
                log.seek(0)
                sys.stderr.write(log.read())
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise RuntimeError(
                        "Production command needed forced shutdown"
                    ) from None
            if (
                process.returncode not in (0, -signal.SIGTERM)
                or not (directory / "shutdown.json").exists()
            ):
                raise RuntimeError("Production command did not shut down gracefully")
        after = validate_cache(cache)
        after["embedding_provenance"] = before["embedding_provenance"] = (
            "synthetic fixture; identical 1536-dimensional vectors"
        )
        if (
            before["files"][str(INDEX_CACHE)] != after["files"][str(INDEX_CACHE)]
            or before["files"][str(DOCUMENT_CACHE)]["sha256"]
            != after["files"][str(DOCUMENT_CACHE)]["sha256"]
        ):
            raise RuntimeError("Persisted embeddings/index were not reused")
        return {
            "port": port,
            "command": command,
            "cache_reused": True,
            "startup_model_requests": 0,
            "health_model_requests": 0,
            "question_provider_requests": counts(),
            "memory": memory,
            "startup_os_peak_rss_bytes": json.loads(
                (directory / "ready.json").read_text()
            )["os_peak_rss_bytes"],
            "os_lifetime_peak_rss_bytes": json.loads(
                (directory / "shutdown.json").read_text()
            )["os_peak_rss_bytes"],
            "cgroup_directory": str(cgroup) if cgroup else None,
            "container_memory_status": (
                "measured"
                if any(phase["cgroup_samples"] for phase in memory.values())
                else "pending; unavailable"
            ),
            "cache": after,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cache = Path(os.environ["NASA_RAG_CACHE_DIR"])
    if args.mode == "seed":
        report = seed(cache)
    else:
        command = args.command
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            parser.error("run requires the inspected image command")
        report = run(cache, command)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
