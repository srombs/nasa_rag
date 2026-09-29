# nasa-rag

A Python foundation for a retrieval-augmented generation project using NASA data.

Install the project dependencies with `uv sync`, then run the examples below
with `uv run python ...`. This ensures optional retrieval dependencies such as
`rank-bm25` are available; the system `python3` interpreter may not have them.

The search script reads every `.txt` file in `data/`, chunks and embeds each
file separately, and retains its filename on every `DocumentChunk` result.

The ingestion responsibilities are split into `file_loader.py`, `chunkers.py`,
and `embedder.py`; the shared `DocumentChunk` object is defined in `models.py`.
Embeddings are cached as `cache/document_cache.json`, keyed by source filename,
so a previously loaded file is not embedded again.
Embedding requests are logged at `INFO` level with the source filename and
number of chunks sent.
`embed_texts` returns embeddings as a NumPy `float32` matrix for FAISS use.
The CLI creates an exact inner-product FAISS index from the document matrix.
Query embeddings are also converted to one-row, L2-normalized matrices.
The FAISS index is persisted in `cache/document.index` and reused when it
matches the current document matrix.
The CLI searches the index with the normalized query matrix and returns the
top 30 matching chunks by default.
`Retriever` owns document loading and delegates vector indexing and search
to its `FaissRetriever`, and raw token indexing to its `BM25Retriever`, which
uses `tokenize_text` and includes every word.
`generator.build_context(results)` formats retrieved chunks for
`generator.generate_answer(context, question)`, which produces a
context-grounded answer using the OpenAI Responses API and `gpt-5.6-luna`.
Chunk references use `[source.txt, chunk N]`; `generator.build_chunk_references`
returns those printable keys as a list for validation against the model answer.
Answers with unrecognized citations receive a validation warning before they
are printed.

Add `--generate-answer` to `semantic_search.py` to retrieve chunks and then
generate an answer from their combined context.

Inspect the answer-level retrieval cases in `eval/eval_100_20.json` with:

```bash
uv run python eval/run_retrieval_evaluation.py
```

The dataset metadata records the `100`-word chunk size and `20`-word overlap
used to label its chunk references. Scoring runners reject different chunk
settings because those references would point to different passages.

Run FAISS retrieval against those expected chunk references with:

```bash
uv run python eval/run_faiss_retrieval_evaluation.py
```

Compare multiple retrieval methods and top-K values while retrieving only once
per question for each method:

```bash
uv run python eval/run_retrieval_top_k_evaluation.py --top-k-values 1 3 5 10 30
```

That runner evaluates FAISS, BM25, and RRF by default. RRF fuses the top 30
FAISS and BM25 candidates with `rrf_k=60`, then evaluates K values `1`, `3`,
`5`, and `10`. Use `--search-method faiss`, `bm25`, `both`, or `rrf` to run a
subset. In combined mode, it rewrites each question once and supplies the same
rewritten query to both base methods.

Add `--enable-reranker` to also evaluate the model reranker over the top 10
RRF candidates. The reranker uses the original question and makes one model
call for each RRF candidate.

The evaluator compares canonical `[source.txt, chunk N]` references and
reports chunk Hit@K plus macro-average chunk Recall@K. Cases with no relevant
chunks are displayed as skipped and do not affect either metric, because FAISS
always returns ranked chunks.

Both search commands accept `--chunk-size`, `--overlap-size`, and `--top-k`
(defaults: `100`, `20`, and `30`). Non-default chunk settings use their own
document and FAISS cache files under `cache/`.

Run BM25 retrieval (without an embedding request for the query) with:

```bash
uv run python semantic_search.py "What powers the ISS?" --bm25-search --top-k 3
```

BM25 retrieval returns `BM25SearchResult(score, chunk)` objects.

Compare FAISS, BM25, and reciprocal-rank-fusion rankings in one run with:

```bash
uv run python semantic_search.py "What powers the ISS?" --both-searches --top-k 3
```

This prints the requested FAISS and BM25 result counts, then the top 10 RRF
results by default, followed by model-reranked RRF results.

`Retriever.search_rrf(query, top_k, rrf_k=60)` fuses FAISS and BM25 rankings
with `1 / (rrf_k + rank)` and stores the combined value in `chunk.rrf_score`.
It also stores each source rank in `chunk.faiss_rank` and `chunk.bm25_rank`.
`Reranker.rerank(query, rrf_results)` sends each query-chunk pair to the model
and returns `RerankResult(chunk, score, reason)` objects for a second-pass
ranking of RRF candidates.
`QueryRewriter().rewrite(query)` sends the original user query to the model,
using its built-in search-query rewrite instructions, and returns the rewritten
search query. FAISS, BM25, and RRF use that rewritten query; the model
reranker receives the original user query and each RRF chunk.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
nasa-rag
```

## Development

```bash
pytest
ruff check .
```

```
Base eval 100/20 - Chunk size 100, overlap 20.

FAISS results
top_k | hit_at_k        | mean_recall_at_k
------|-----------------|-----------------
    1 | 11/23 (47.8%) | 24.6%
    3 | 17/23 (73.9%) | 44.9%
    5 | 18/23 (78.3%) | 54.2%

BM25 results
top_k | hit_at_k        | mean_recall_at_k
------|-----------------|-----------------
    1 |  9/23 (39.1%) | 19.3%
    3 | 12/23 (52.2%) | 28.5%
    5 | 12/23 (52.2%) | 29.6%

RRF results
top_k | hit_at_k        | mean_recall_at_k
------|-----------------|-----------------
    1 | 12/23 (52.2%) | 25.4%
    3 | 15/23 (65.2%) | 35.9%
    5 | 18/23 (78.3%) | 43.6%
   10 | 19/23 (82.6%) | 58.3%

RERANKER results
top_k | hit_at_k        | mean_recall_at_k
------|-----------------|-----------------
    1 | 16/23 (69.6%) | 34.1%
    3 | 19/23 (82.6%) | 53.8%
    5 | 19/23 (82.6%) | 57.2%
   10 | 19/23 (82.6%) | 58.3%
```
