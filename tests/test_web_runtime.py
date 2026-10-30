"""Exercise the profiling command as an operator, without model requests."""

import json
import os
import subprocess
import sys
from threading import Event

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("psutil")
pytestmark = pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"}, reason="Unix profiling procedure"
)


@pytest.fixture
def persisted_cache(tmp_path):
    from nasa_rag.ingestion.chunkers import chunk_text
    from nasa_rag.ingestion.file_loader import save_document_cache
    from nasa_rag.models import DocumentChunk
    from nasa_rag.paths import data_directory
    from nasa_rag.retrieval.retriever import Retriever

    cache = tmp_path / "cache"
    documents = {
        source.name: [
            DocumentChunk(source.name, i, text, [1.0, 0.5, 0.25, 0.125])
            for i, text in enumerate(chunk_text(source.read_text(), 100, 20))
        ]
        for source in sorted(data_directory().glob("*.txt"))
    }
    save_document_cache(cache / "embeds/document_cache_100_20.json", documents)
    Retriever(data_directory(), cache_directory=cache).load()
    return cache


def test_profile_command_runs_two_servers_offline_and_reports_real_process_memory(
    persisted_cache, tmp_path
):
    report_path = tmp_path / "measurement.json"
    index = persisted_cache / "faiss/document_100_20.index"
    original_index_time = index.stat().st_mtime_ns
    environment = {**os.environ, "OPENAI_API_KEY": "must-never-be-used"}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/profile_web_runtime.py",
            "--cache-dir",
            str(persisted_cache),
            "--output",
            str(report_path),
            "--idle-seconds",
            "0.1",
            "--sample-interval",
            "0.005",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text())
    assert report["observation"] == "local/provisional"
    assert report["provider_mode"] == "mocked_http"
    assert report["cache"]["dimensions"] == 4
    assert report["cache"]["chunks"] == 737
    assert report["cache"]["embedding_provenance"] == "operator-supplied; unverified"
    assert len(report["runs"]) == 2
    assert report["runs"][0]["pid"] != report["runs"][1]["pid"]
    for run in report["runs"]:
        assert run["cache_reused"] is True
        assert run["health_model_requests"] == 0
        assert run["startup_model_requests"] == 0
        assert run["question_model_requests"] == 13
        assert run["question_status"] == 200
        assert run["memory"]["startup"]["rss_peak_bytes"] > 0
        assert run["memory"]["idle"]["rss_mean_bytes"] > 0
        assert run["memory"]["question"]["rss_peak_bytes"] > 0
        assert run["os_peak_rss_bytes"] > 0
    assert index.stat().st_mtime_ns == original_index_time
    assert "must-never-be-used" not in report_path.read_text() + result.stdout


def test_profile_command_rejects_missing_cache_before_starting_server(tmp_path):
    output = tmp_path / "not-measured.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/profile_web_runtime.py",
            "--cache-dir",
            str(tmp_path / "missing"),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "compatible persisted" in result.stderr
    assert not output.exists()


def test_unavailable_container_counter_does_not_truncate_rss_observation(tmp_path):
    from scripts.profile_web_runtime import measure

    # A directory in place of a counter exercises a real filesystem read failure.
    (tmp_path / "memory.current").mkdir()
    _, memory = measure(os.getpid(), lambda: Event().wait(0.05), 0.005, tmp_path)
    assert memory["samples"] >= 2
    assert memory["cgroup_current_peak_bytes"] is None
    assert memory["rss_peak_bytes"] > 0
