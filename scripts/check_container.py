"""Build and check the production Linux image without credentials or model calls."""

import argparse
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

IMPORT_CHECK = """
import importlib.util
import faiss
import nasa_rag.web
from nasa_rag.paths import data_directory
from pathlib import Path
assert '/app/.venv/' in nasa_rag.web.__file__
assert sorted(p.name for p in data_directory().glob('*.txt')) == [
    'hubble.txt', 'iss.txt', 'nasa_overview.txt', 'space_shuttle.txt'
]
assert all(importlib.util.find_spec(p) is None for p in ('pytest', 'ruff', 'psutil'))
assert not Path('/data/cache').exists()
assert not Path('/data/logs').exists()
print('Installed package, FAISS, bundled documents, and import isolation: OK')
"""


def docker(*arguments, timeout=180):
    result = subprocess.run(
        ["docker", *map(str, arguments)],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="nasa-rag:check")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parent.parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Fail clearly rather than treating absent Docker as a passing/skip result.
    docker("info")
    if not args.skip_build:
        print("Building production Dockerfile (no credentials)...", flush=True)
        docker("build", "--tag", args.image, repository, timeout=900)
    image = json.loads(docker("image", "inspect", args.image))[0]
    if image["Os"] != "linux":
        raise RuntimeError("Container verification requires a Linux image")
    command = (image["Config"].get("Entrypoint") or []) + image["Config"]["Cmd"]
    image_id = image["Id"]
    print(
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "python",
            image_id,
            "-c",
            IMPORT_CHECK,
        ).strip(),
        flush=True,
    )
    token = uuid4().hex[:12]
    volume = f"nasa-rag-check-{token}"
    containers = []
    report = {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "status": "pending",
        "observation": "Linux container; synthetic warm cache; mocked provider HTTP",
        "image_id": image_id,
        "architecture": image["Architecture"],
        "controller_platform": platform.platform(),
        "production_command": command,
        "provider_mode": "mocked_http; container network disabled",
        "measurement_notes": [
            "Process RSS is sampled every 0.01s; peaks are sampled lower bounds.",
            "OS process peaks include startup and are lifetime high-water marks.",
            "Container cgroup includes the probe, page cache, and server.",
            "Unreadable container counters are null/pending, never zero.",
            "Synthetic 1536-dimensional embeddings; no cold ingestion measured.",
            "Mock latency/output are not real provider or Railway capacity evidence.",
            "Two seconds of idle per phase; no sustained-traffic measurement.",
        ],
        "runs": [],
    }
    try:
        docker("volume", "create", volume)
        for mode in ("seed", "run-1", "run-2"):
            name = f"{volume}-{mode}"
            containers.append(name)
            filename = f"{mode}.json"
            arguments = [
                "run",
                "--name",
                name,
                "--network",
                "none",
                "--mount",
                f"type=volume,source={volume},target=/data",
                "--mount",
                f"type=bind,source={repository / 'scripts'},target=/checks,readonly",
                "--env",
                "PORT=8765",
                "--entrypoint",
                "python",
                image_id,
                "/checks/container_runtime_check.py",
                "--output",
                f"/data/{filename}",
                "seed" if mode == "seed" else "run",
            ]
            if mode != "seed":
                arguments += ["--", *command]
            print(f"Checking {mode}...", flush=True)
            docker(*arguments)
            with TemporaryDirectory(prefix="nasa-rag-report-") as temporary:
                target = Path(temporary) / filename
                docker("cp", f"{name}:/data/{filename}", target)
                observation = json.loads(target.read_text())
            if mode == "seed":
                report["fixture"] = observation
            else:
                observation["container_id"] = docker(
                    "inspect", "--format", "{{.Id}}", name
                ).strip()
                report["runs"].append(observation)
        report["status"] = "passed"
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        for name in containers:
            subprocess.run(
                ["docker", "rm", "--force", name], capture_output=True, timeout=30
            )
        subprocess.run(
            ["docker", "volume", "rm", volume], capture_output=True, timeout=30
        )
    print(f"Container checks passed; wrote {args.output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Docker check failed:\n{error.stdout}\n{error.stderr}"
        ) from None
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Docker verification unavailable/failed: {error}") from None
