"""Profile two single-process API starts; default OpenAI transport is offline."""

import argparse
import hashlib
import io
import json
import math
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.request import ProxyHandler, Request, build_opener

DOCUMENT_CACHE = Path("embeds/document_cache_100_20.json")
INDEX_CACHE = Path("faiss/document_100_20.index")
QUESTION = "What mission launched Hubble?"


def fingerprint(path: Path) -> dict:
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mtime_ns": path.stat().st_mtime_ns,
    }


def validate_cache(cache: Path) -> dict:
    """Reject missing/stale inputs without starting a server or requesting models."""
    import faiss
    import numpy as np

    from nasa_rag.ingestion.chunkers import chunk_text
    from nasa_rag.paths import data_directory

    if not all((cache / path).is_file() for path in (DOCUMENT_CACHE, INDEX_CACHE)):
        raise ValueError("Provide compatible persisted document and FAISS caches.")
    documents = json.loads((cache / DOCUMENT_CACHE).read_text())["documents"]
    sources = sorted(data_directory().glob("*.txt"))
    if set(documents) != {source.name for source in sources}:
        raise ValueError("Cached sources do not match the bundled corpus.")
    records = []
    for source in sources:
        with redirect_stdout(io.StringIO()):
            expected = chunk_text(source.read_text(), 100, 20)
        cached = documents[source.name]
        if len(cached) != len(expected) or any(
            item["text"] != text
            or item["source"] != source.name
            or item["chunk_index"] != i
            for i, (item, text) in enumerate(zip(cached, expected, strict=True))
        ):
            raise ValueError(f"Cached chunks do not match {source.name} at 100/20.")
        records.extend(cached)
    matrix = np.array([item["embed"] for item in records], dtype=np.float32)
    if matrix.ndim != 2 or not matrix.shape[1] or not np.isfinite(matrix).all():
        raise ValueError("Invalid cached embedding matrix.")
    if np.any(np.linalg.norm(matrix, axis=1) == 0):
        raise ValueError("Cached embeddings contain zero vectors.")
    index = faiss.read_index(str(cache / INDEX_CACHE))
    faiss.normalize_L2(matrix)
    if (
        not isinstance(index, faiss.IndexFlatIP)
        or index.ntotal != len(records)
        or index.d != matrix.shape[1]
        or not np.allclose(index.reconstruct_n(), matrix, atol=1e-6)
    ):
        raise ValueError("FAISS cache does not match the document embeddings.")
    return {
        "chunks": len(records),
        "dimensions": matrix.shape[1],
        "embedding_provenance": "operator-supplied; unverified",
        "files": {
            str(p): fingerprint(cache / p) for p in (DOCUMENT_CACHE, INDEX_CACHE)
        },
        "sources": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
    }


def cgroup_directory(pid: int) -> Path | None:
    """Locate a readable Linux cgroup v2; never substitute host memory."""
    if sys.platform != "linux":
        return None
    try:
        groups = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
        mounts = Path(f"/proc/{pid}/mountinfo").read_text().splitlines()
    except OSError:
        return None
    group = next((p[3:] for p in groups if p.startswith("0::")), None)
    if group is not None:
        for mount in mounts:
            fields = mount.split()
            if mount.split(" - ")[1].split()[0] != "cgroup2":
                continue
            try:
                relative = Path(group).relative_to(fields[3])
            except ValueError:
                continue
            directory = Path(fields[4]) / relative
            if (directory / "memory.current").is_file():
                return directory
    return None


def read_counter(directory: Path | None, name: str) -> int | None:
    if directory is None:
        return None
    try:
        return int((directory / name).read_text())
    except (OSError, ValueError):
        return None


def measure(pid: int, action, interval: float, cgroup: Path | None) -> tuple:
    import psutil

    process = psutil.Process(pid)
    samples: list[int] = []
    container_samples: list[int] = []
    stopped = Event()

    def sample():
        while not stopped.is_set():
            try:
                samples.append(process.memory_info().rss)
            except psutil.Error as error:
                sampling_errors.append(str(error))
                return
            current = read_counter(cgroup, "memory.current")
            if current is not None:
                container_samples.append(current)
            stopped.wait(interval)

    sampling_errors: list[str] = []
    sampler = Thread(target=sample, daemon=True)
    sampler.start()
    try:
        result = action()
    finally:
        stopped.set()
        sampler.join()
    if sampling_errors or not samples:
        raise RuntimeError("Worker RSS observation failed or ended prematurely.")
    summary = {
        "rss_peak_bytes": max(samples),
        "rss_mean_bytes": sum(samples) / len(samples),
        "rss_min_bytes": min(samples),
        "samples": len(samples),
        "cgroup_current_peak_bytes": max(container_samples)
        if container_samples
        else None,
        "cgroup_current_mean_bytes": (
            sum(container_samples) / len(container_samples)
            if container_samples
            else None
        ),
        "cgroup_samples": len(container_samples),
        "cgroup_lifetime_peak_bytes": read_counter(cgroup, "memory.peak"),
    }
    return result, summary


def run_once(args, cache: Path, directory: Path, dimensions: int) -> dict:
    state = directory / "state.json"
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    environment = {
        **os.environ,
        "NASA_RAG_CACHE_DIR": str(cache),
        "NASA_RAG_COST_LOG_PATH": str(directory / "costs.jsonl"),
        "NASA_RAG_TRUSTED_PROXIES": "",
    }
    if not args.live:
        environment["OPENAI_API_KEY"] = "offline-profile-placeholder"
    command = [
        sys.executable,
        str(Path(__file__).with_name("runtime_mock_provider.py")),
        "--fd",
        str(listener.fileno()),
        "--state",
        str(state),
        "--dimensions",
        str(dimensions),
    ]
    if args.live:
        command.append("--live")
    before_index = fingerprint(cache / INDEX_CACHE)
    opener = build_opener(ProxyHandler({}))
    memory = {}
    started = time.monotonic()
    with (directory / "server.log").open("w+") as log:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=log,
            stderr=log,
            pass_fds=(listener.fileno(),),
        )
        listener.close()

        def wait_for(phase, occurrences=1):
            deadline = time.monotonic() + args.startup_timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Profiling server exited before verification.")
                if state.exists():
                    records = json.loads(state.read_text())
                    if (
                        records[-1]["phase"] == phase
                        and sum(r["phase"] == phase for r in records) >= occurrences
                    ):
                        return records[-1]
                time.sleep(0.01)
            raise RuntimeError(f"Timed out waiting for profiling phase {phase}.")

        def request(path, body=None):
            data = json.dumps(body).encode() if body is not None else None
            with opener.open(
                Request(
                    url + path, data=data, headers={"Content-Type": "application/json"}
                ),
                timeout=args.request_timeout,
            ) as response:
                payload = json.load(response)
                return response.status, payload

        try:
            cgroup = cgroup_directory(process.pid)
            startup, memory["startup"] = measure(
                process.pid,
                lambda: wait_for("startup"),
                args.sample_interval,
                cgroup,
            )
            startup_seconds = time.monotonic() - started
            _, memory["idle"] = measure(
                process.pid,
                lambda: time.sleep(args.idle_seconds),
                args.sample_interval,
                cgroup,
            )
            for _ in range(3):
                if request("/health") != (200, {"status": "ok"}):
                    raise RuntimeError("Health smoke check failed.")
            health = wait_for("/health", occurrences=3)
            question_started = time.monotonic()
            response, memory["question"] = measure(
                process.pid,
                lambda: request("/ask", {"question": QUESTION}),
                args.sample_interval,
                cgroup,
            )
            question_seconds = time.monotonic() - question_started
            question = wait_for("/ask")
            if response[0] != 200 or set(response[1]) != {"request_id", "answer"}:
                raise RuntimeError("Question smoke check failed.")
            _, memory["post_question_idle"] = measure(
                process.pid,
                lambda: time.sleep(args.idle_seconds),
                args.sample_interval,
                cgroup,
            )
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError(
                    "Profiling server required forced shutdown."
                ) from None
        if process.returncode not in (0, -signal.SIGTERM):
            raise RuntimeError("Profiling server did not shut down successfully.")
    final = json.loads(state.read_text())[-1]
    if final["phase"] != "shutdown":
        raise RuntimeError("Profiling server did not complete lifespan shutdown.")
    startup_calls = sum(startup["requests"].values())
    health_calls = sum(health["requests"].values()) - startup_calls
    reused = before_index == fingerprint(cache / INDEX_CACHE) and startup_calls == 0
    if not reused or health_calls:
        raise RuntimeError("Cache reuse/model-free health verification failed.")
    return {
        "pid": process.pid,
        "cache_reused": reused,
        "startup_model_requests": startup_calls,
        "health_model_requests": health_calls,
        "question_model_requests": sum(question["requests"].values()) - startup_calls,
        "provider_requests": question["requests"],
        "question_status": response[0],
        "startup_seconds": startup_seconds,
        "question_seconds": question_seconds,
        "memory": memory,
        "startup_os_peak_rss_bytes": startup["os_peak_rss_bytes"],
        "question_os_lifetime_peak_rss_bytes": question["os_peak_rss_bytes"],
        "os_peak_rss_bytes": final["os_peak_rss_bytes"],
        "cgroup_directory": str(cgroup) if cgroup else None,
    }


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--idle-seconds", type=positive, default=2.0)
    parser.add_argument("--sample-interval", type=positive, default=0.01)
    parser.add_argument("--startup-timeout", type=positive, default=60.0)
    parser.add_argument("--request-timeout", type=positive, default=150.0)
    parser.add_argument(
        "--live",
        action="store_true",
        help="make real model calls for TWO questions; requires approval",
    )
    args = parser.parse_args()
    if sys.platform not in {"linux", "darwin"}:
        parser.error("This profiling procedure supports Linux and macOS.")
    if args.live and not os.environ.get("OPENAI_API_KEY", "").strip():
        parser.error("Live profiling requires OPENAI_API_KEY in the environment.")
    try:
        metadata = validate_cache(args.cache_dir)
        with TemporaryDirectory(prefix="nasa-rag-profile-") as temporary:
            root = Path(temporary)
            cache = root / "cache"
            for path in (DOCUMENT_CACHE, INDEX_CACHE):
                (cache / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(args.cache_dir / path, cache / path)
            runs = []
            for i in range(2):
                directory = root / f"run-{i + 1}"
                directory.mkdir()
                runs.append(run_once(args, cache, directory, metadata["dimensions"]))
        report = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "observation": "local/provisional",
            "provider_mode": "live" if args.live else "mocked_http",
            "pipeline": "unchanged full hybrid API with request controls",
            "question": QUESTION,
            "cache": metadata,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "packages": {
                    p: version(p)
                    for p in (
                        "nasa-rag",
                        "numpy",
                        "faiss-cpu",
                        "openai",
                        "fastapi",
                        "uvicorn",
                        "httpx",
                        "psutil",
                        "rank-bm25",
                    )
                },
            },
            "settings": {
                "workers": 1,
                "chunk_size": 100,
                "overlap_size": 20,
                "top_k": 30,
                "rrf_top_k": 10,
                "rrf_k": 60,
                "response_timeout_seconds": os.environ.get(
                    "NASA_RAG_RESPONSE_TIMEOUT_SECONDS", "120"
                ),
                "trusted_proxies": "",
                "bind": "127.0.0.1:ephemeral",
                "sample_interval_seconds": args.sample_interval,
                "idle_seconds": args.idle_seconds,
                "cache_state": "warm persisted copy",
            },
            "measurement_notes": [
                "Only worker RSS is sampled; profiler/test runner RSS is excluded.",
                "Phase peaks are sampled lower bounds; OS peaks are lifetime maxima.",
                "cgroup values may include the profiler and other processes.",
                "cgroup lifetime peaks may predate this run and are never reset.",
                "Mock HTTP omits real network/TLS, latency, and output variability.",
                "Deployed service memory and billing remain pending.",
            ],
            "runs": runs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        parser.exit(1, f"Profiling failed: {error}\n")
    print(f"Wrote {args.output} ({report['provider_mode']}; local/provisional)")


if __name__ == "__main__":
    main()
