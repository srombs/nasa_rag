import json
import sys
import types

import embedder
import file_loader
import numpy as np
import semantic_search
import vector_store
from models import DocumentChunk

from nasa_rag import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_load_and_embed_directory_caches_each_text_file(monkeypatch, tmp_path) -> None:
    (tmp_path / "b.txt").write_text("four five", encoding="utf-8")
    (tmp_path / "a.txt").write_text("one two three", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("not a source", encoding="utf-8")

    embedded_inputs: list[tuple[list[str], str]] = []

    def fake_embed_documents(texts, source):
        text_list = list(texts)
        embedded_inputs.append((text_list, source))
        return [
            DocumentChunk(source, index, text, [float(index)])
            for index, text in enumerate(text_list)
        ]

    monkeypatch.setattr(file_loader, "embed_documents", fake_embed_documents)

    chunks = file_loader.load_and_embed_directory(
        tmp_path, chunk_size=2, overlap_size=0
    )

    assert embedded_inputs == [
        (["one two", "three"], "a.txt"),
        (["four five"], "b.txt"),
    ]
    assert [(chunk.source, chunk.chunk_index, chunk.text) for chunk in chunks] == [
        ("a.txt", 0, "one two"),
        ("a.txt", 1, "three"),
        ("b.txt", 0, "four five"),
    ]

    cache_path = tmp_path / file_loader.CACHE_FILE_NAME
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {
        "documents": {
            "a.txt": [
                {
                    "source": "a.txt",
                    "chunk_index": 0,
                    "text": "one two",
                    "embed": [0.0],
                },
                {
                    "source": "a.txt",
                    "chunk_index": 1,
                    "text": "three",
                    "embed": [1.0],
                },
            ],
            "b.txt": [
                {
                    "source": "b.txt",
                    "chunk_index": 0,
                    "text": "four five",
                    "embed": [0.0],
                }
            ],
        }
    }

    cached_chunks = file_loader.load_and_embed_directory(
        tmp_path, chunk_size=2, overlap_size=0
    )

    assert embedded_inputs == [
        (["one two", "three"], "a.txt"),
        (["four five"], "b.txt"),
    ]
    assert cached_chunks == chunks


def test_print_ranked_chunks_uses_top_k(capsys) -> None:
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0], similarity=0.9),
        DocumentChunk("b.txt", 0, "second", [1.0], similarity=0.8),
    ]

    semantic_search.print_ranked_chunks(chunks, top_k=1)

    assert capsys.readouterr().out == "0.9000 | a.txt | chunk 0 | first\n"


def test_embed_texts_returns_a_float32_matrix(monkeypatch) -> None:
    response = types.SimpleNamespace(
        data=[
            types.SimpleNamespace(index=1, embedding=[3.0, 4.0]),
            types.SimpleNamespace(index=0, embedding=[1.0, 2.0]),
        ]
    )
    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "embeddings",
                types.SimpleNamespace(create=lambda **kwargs: response),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    embeddings = embedder.embed_texts(["first", "second"], source="nasa.txt")

    assert embeddings.dtype == np.float32
    assert embeddings.shape == (2, 2)
    assert embeddings.tolist() == [[1.0, 2.0], [3.0, 4.0]]


def test_create_index_adds_every_embedding_vector() -> None:
    matrix = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)

    index = vector_store.create_index(matrix)

    assert index.d == 2
    assert index.ntotal == 2
    indexed_vectors = index.reconstruct_n(0, 2)
    assert np.allclose(np.linalg.norm(indexed_vectors, axis=1), [1.0, 1.0])
    scores, indexes = index.search(
        np.array([[0.6, 0.8]], dtype=np.float32), k=1
    )
    assert scores.tolist() == [[1.0]]
    assert indexes.tolist() == [[0]]


def test_create_query_matrix_normalizes_the_query_embedding() -> None:
    query_matrix = vector_store.create_query_matrix([3.0, 4.0])

    assert query_matrix.dtype == np.float32
    assert query_matrix.shape == (1, 2)
    assert np.allclose(query_matrix, [[0.6, 0.8]])
    assert np.allclose(np.linalg.norm(query_matrix, axis=1), [1.0])


def test_search_faiss_returns_the_top_k_document_chunks() -> None:
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0, 0.0]),
        DocumentChunk("b.txt", 0, "second", [0.0, 1.0]),
    ]
    matrix = np.array([chunk.embed for chunk in chunks], dtype=np.float32)
    index = vector_store.create_index(matrix)
    query_matrix = vector_store.create_query_matrix([1.0, 0.0])

    ranked_chunks = semantic_search.search_faiss(
        index, query_matrix, chunks, top_k=1
    )

    assert ranked_chunks == [chunks[0]]
    assert ranked_chunks[0].similarity == 1.0


def test_load_or_create_index_reuses_a_compatible_cache(monkeypatch, tmp_path) -> None:
    matrix = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float32)
    cache_path = tmp_path / "document.index"

    created_index = vector_store.load_or_create_index(matrix, cache_path)

    def fail_if_called(_matrix):
        raise AssertionError("A compatible FAISS cache should be reused.")

    monkeypatch.setattr(vector_store, "create_index", fail_if_called)
    cached_index = vector_store.load_or_create_index(matrix, cache_path)

    assert cache_path.is_file()
    assert created_index.ntotal == cached_index.ntotal == 2
    assert created_index.d == cached_index.d == 2
