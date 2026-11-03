"""Test-only hook, mounted outside the image and enabled only for its child."""

import asyncio
import json
import os
import resource
import time
from contextlib import asynccontextmanager
from pathlib import Path


def install() -> None:
    from runtime_mock_provider import install_provider

    directory = Path(os.environ["NASA_RAG_CONTAINER_CHECK_DIR"])

    def write(name, value):
        target = directory / name
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(value))
        temporary.replace(target)

    def count(kind):
        write("provider.json", dict(requests))
        if kind == "retrieval_plan":
            deadline = time.monotonic() + 30
            while not (directory / "question.release").exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Container check did not release the question")
                time.sleep(0.01)

    requests = install_provider(1536, on_request=count)
    write("provider.json", {})

    # Observe the actual app's lifespan, retaining its real retriever/pipeline.
    from nasa_rag.web import app

    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def observed_lifespan(application):
        (directory / "startup.entered").touch()
        deadline = time.monotonic() + 30
        while not (directory / "startup.release").exists():
            if time.monotonic() >= deadline:
                raise RuntimeError("Container check did not release startup")
            await asyncio.sleep(0.01)
        async with lifespan(application) as state:
            write("ready.json", {"os_peak_rss_bytes": peak_rss()})
            yield state
        write("shutdown.json", {"os_peak_rss_bytes": peak_rss()})

    app.router.lifespan_context = observed_lifespan


def peak_rss():
    import sys

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


if os.environ.get("NASA_RAG_CONTAINER_CHECK_DIR"):
    try:
        install()
    except Exception:
        # Python normally ignores sitecustomize errors; a broken check must fail.
        import traceback

        traceback.print_exc()
        os._exit(1)
