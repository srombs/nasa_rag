"""Private profiling worker: actual API, optional OpenAI HTTP substitution."""

import argparse
import json
import resource
import socket
import sys
from collections import Counter
from pathlib import Path

import httpx
import openai
import uvicorn


def serve(fd: int, state_path: Path, dimensions: int, live: bool) -> None:
    requests: Counter[str] = Counter()
    snapshots = []
    real_openai = openai.OpenAI

    def count(request: httpx.Request) -> None:
        payload = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            kind = (
                "query_embedding"
                if isinstance(payload["input"], str)
                else "document_embedding"
            )
        elif request.url.path.endswith("/responses"):
            kind = payload.get("text", {}).get("format", {}).get("name", "answer")
        else:
            raise RuntimeError("Unexpected provider endpoint")
        requests[kind] += 1
        if kind == "document_embedding":
            raise RuntimeError("Profiling requires compatible persisted embeddings")

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            body = {
                "object": "list",
                "model": payload["model"],
                "data": [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [1.0] + [0.0] * (dimensions - 1),
                    }
                ],
            }
        else:
            kind = payload.get("text", {}).get("format", {}).get("name")
            if kind == "retrieval_plan":
                output = json.dumps(
                    {
                        "search_query": payload["input"],
                        "source_file_filter": None,
                    }
                )
            elif kind == "rerank_result":
                output = '{"score": 0.8, "reason": "Mock evidence score"}'
            elif kind is None:
                output = "Mock answer: this run measures memory, not answer quality."
            else:
                raise RuntimeError("Unexpected provider response format")
            body = {
                "id": "resp_profile",
                "object": "response",
                "created_at": 0,
                "model": payload["model"],
                "status": "completed",
                "output": [
                    {
                        "id": "msg_profile",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": output, "annotations": []}
                        ],
                    }
                ],
            }
        return httpx.Response(200, json=body)

    def client(*args, **kwargs):
        kwargs["http_client"] = httpx.Client(
            transport=None if live else httpx.MockTransport(respond),
            event_hooks={"request": [count]},
        )
        return real_openai(*args, **kwargs)

    setattr(openai, "OpenAI", client)

    # Import only after installing the external-provider boundary.
    from nasa_rag.web import create_app

    app = create_app()

    def snapshot(phase: str) -> None:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        snapshots.append(
            {
                "phase": phase,
                "requests": dict(requests),
                "os_peak_rss_bytes": int(
                    peak if sys.platform == "darwin" else peak * 1024
                ),
            }
        )
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshots))
        temporary.replace(state_path)

    async def observed(scope, receive, send):
        async def observed_send(message):
            if message["type"] == "lifespan.startup.complete":
                snapshot("startup")
            elif message["type"] == "lifespan.shutdown.complete":
                snapshot("shutdown")
            await send(message)

        await app(scope, receive, observed_send)
        if scope["type"] == "http":
            snapshot(scope["path"])

    uvicorn.Server(
        uvicorn.Config(
            observed,
            host="127.0.0.1",
            workers=1,
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
    ).run(sockets=[socket.socket(fileno=fd)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fd", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--dimensions", type=int, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    serve(args.fd, args.state, args.dimensions, args.live)
