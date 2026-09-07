# nasa-rag

A Python foundation for a retrieval-augmented generation project using NASA data.

The search script reads every `.txt` file in `data/`, chunks and embeds each
file separately, and retains its filename on every `DocumentChunk` result.

The ingestion responsibilities are split into `file_loader.py`, `chunkers.py`,
and `embedder.py`; the shared `DocumentChunk` object is defined in `models.py`.
Embeddings are cached as `data/document_cache.json`, keyed by source filename,
so a previously loaded file is not embedded again.
Embedding requests are logged at `INFO` level with the source filename and
number of chunks sent.
`embed_texts` returns embeddings as a NumPy `float32` matrix for FAISS use.
The CLI creates an exact inner-product FAISS index from the document matrix.

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
