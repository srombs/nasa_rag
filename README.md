# nasa-rag

A Python foundation for a retrieval-augmented generation project using NASA data.

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
top three matching chunks.
`Retriever` owns document loading and tokenization, then delegates vector
indexing and search to its `FaissRetriever`. `tokenizer.tokenize_chunks`
creates standalone `TokenizedChunk` objects containing a source, chunk index,
and normalized token set. `Retriever.search_keywords(query, top_k)` ranks
those chunks by the fraction of unique query tokens found in each chunk.
`generator.build_context(results)` formats retrieved chunks for
`generator.generate_answer(context, question)`, which produces a
context-grounded answer using the OpenAI Responses API and `gpt-5.6-luna`.
Chunk references use `[source.txt, chunk N]`; `generator.build_chunk_references`
returns those printable keys as a list for validation against the model answer.
Answers with unrecognized citations receive a validation warning before they
are printed.

Add `--generate-answer` to `semantic_search.py` to retrieve chunks and then
generate an answer from their combined context.

Run the question evaluation loop with:

```bash
python3 eval/run_evaluation.py
```

Both search commands accept `--chunk-size`, `--overlap-size`, and `--top-k`
(defaults: `100`, `20`, and `3`). Non-default chunk settings use their own
document and FAISS cache files under `cache/`.

Run keyword-overlap retrieval (without an embedding request for the query)
with:

```bash
python3 semantic_search.py "What powers the ISS?" --keyword-search --top-k 3
```

Compare independent FAISS and keyword rankings in one run with:

```bash
python3 semantic_search.py "What powers the ISS?" --both-searches --top-k 3
```

Run weighted hybrid retrieval (FAISS `0.7`, keywords `0.3` by default) with:

```bash
python3 semantic_search.py "What powers the ISS?" --hybrid-search --top-k 3
```

Customize the formula `semantic_weight * semantic_score + keyword_weight *
keyword_score` with `--semantic-weight` and `--keyword-weight`.
Hybrid results retain the `DocumentChunk` plus `semantic_score`, `keyword_score`,
and `hybrid_score` in a `HybridSearchResult` object.
Hybrid CLI mode prints the FAISS ranking first, followed by the hybrid ranking;
both use the same embedded query.

The evaluation reports source-level `Recall@3`: a question is a hit when any
of its expected source files appears among its three retrieved chunks.

Run all combinations of `Recall@1` through `Recall@5` for chunk/overlap
settings `50/10`, `100/20`, and `200/50` with:

```bash
python3 eval/run_grid_evaluation.py
```

The grid run prints only failed questions with their expected source and
retrieved chunks, followed by the recall summary table.

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
