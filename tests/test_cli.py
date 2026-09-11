import json
import logging
import sys
import types

import embedder
import faiss_retriever
import file_loader
import generator
import chunkers
import numpy as np
import retriever
import semantic_search
import tokenizer
import vector_store
from models import DocumentChunk, TokenizedChunk

from nasa_rag import __version__


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_chunk_text_creates_overlapping_word_chunks() -> None:
    chunks = chunkers.chunk_text(
        "one two three four five", chunk_size=3, overlap_size=1
    )

    assert chunks == ["one two three", "three four five"]


def test_chunk_text_rejects_invalid_chunk_settings() -> None:
    invalid_settings = [
        (0, 0),
        (-1, 0),
        (3, -1),
        (3, 3),
        (3, 4),
    ]

    for chunk_size, overlap_size in invalid_settings:
        try:
            chunkers.chunk_text("one two three", chunk_size, overlap_size)
        except ValueError:
            continue
        raise AssertionError("Expected invalid chunk settings to be rejected.")


def test_tokenize_chunks_creates_a_token_set_for_each_chunk() -> None:
    chunks = [
        DocumentChunk("iss.txt", 248, "ISS crews study Mars, Mars!", [1.0]),
        DocumentChunk("hubble.txt", 3, "Hubble observes galaxies.", [1.0]),
    ]

    tokenized_chunks = tokenizer.tokenize_chunks(chunks)

    assert tokenized_chunks == [
        TokenizedChunk("iss.txt", 248, {"iss", "crews", "study", "mars"}),
        TokenizedChunk("hubble.txt", 3, {"hubble", "observes", "galaxies"}),
    ]


def test_score_tokenized_chunks_ranks_normalized_keyword_overlap() -> None:
    chunks = [
        TokenizedChunk("iss.txt", 0, {"iss", "crew", "research"}),
        TokenizedChunk("hubble.txt", 1, {"hubble", "telescope"}),
    ]

    scores = tokenizer.score_tokenized_chunks(
        tokenizer.tokenize_text("ISS research telescope"), chunks
    )

    assert scores == [(chunks[0], 2 / 3), (chunks[1], 1 / 3)]
    assert tokenizer.keyword_score(set(), chunks[0].tokens) == 0.0


def test_retriever_loads_document_tokens_and_faiss(monkeypatch, tmp_path) -> None:
    chunks = [
        DocumentChunk("iss.txt", 248, "ISS crews study Mars.", [1.0, 0.0]),
        DocumentChunk("hubble.txt", 3, "Hubble observes galaxies.", [0.0, 1.0]),
    ]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )

    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()

    assert generic_retriever.document_chunks == chunks
    assert generic_retriever.tokenized_chunks == [
        TokenizedChunk("iss.txt", 248, {"iss", "crews", "study", "mars"}),
        TokenizedChunk("hubble.txt", 3, {"hubble", "observes", "galaxies"}),
    ]
    assert generic_retriever.faiss_retriever.index is not None
    assert generic_retriever.faiss_retriever.index.ntotal == len(chunks)


def test_retriever_search_keywords_returns_matching_document_chunks(
    monkeypatch, tmp_path
) -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS crew research.", [1.0, 0.0]),
        DocumentChunk("hubble.txt", 1, "Hubble telescope.", [0.0, 1.0]),
    ]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )
    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()

    results = generic_retriever.search_keywords("ISS research", top_k=1)

    assert results == [chunks[0]]
    assert results[0].similarity == 1.0


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

    cache_path = tmp_path / "cache" / file_loader.CACHE_FILE_NAME
    chunks = file_loader.load_and_embed_directory(
        tmp_path, chunk_size=2, overlap_size=0, cache_path=cache_path
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
        tmp_path, chunk_size=2, overlap_size=0, cache_path=cache_path
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

    assert capsys.readouterr().out == "0.9000 | [a.txt, chunk 0] | first\n"


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


def test_embed_query_raises_embedding_error_for_api_failure(monkeypatch) -> None:
    def fail_request(**kwargs):
        raise RuntimeError("API unavailable")

    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "embeddings",
                types.SimpleNamespace(create=fail_request),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    try:
        embedder.embed_query("When was NASA founded?")
    except embedder.EmbeddingError as error:
        assert isinstance(error.__cause__, RuntimeError)
        assert str(error) == "Unable to embed the query."
    else:
        raise AssertionError("Expected EmbeddingError for an API failure.")


def test_embed_texts_raises_embedding_error_for_api_failure(monkeypatch) -> None:
    def fail_request(**kwargs):
        raise RuntimeError("API unavailable")

    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "embeddings",
                types.SimpleNamespace(create=fail_request),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    try:
        embedder.embed_texts(["NASA document"], source="nasa.txt")
    except embedder.EmbeddingError as error:
        assert isinstance(error.__cause__, RuntimeError)
        assert str(error) == "Unable to embed text chunks."
    else:
        raise AssertionError("Expected EmbeddingError for an API failure.")


def test_generate_answer_uses_context_and_question(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger=generator.__name__)
    response = types.SimpleNamespace(output_text="NASA was founded in 1958.")
    request = {}

    def create_response(**kwargs):
        request.update(kwargs)
        return response

    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "responses",
                types.SimpleNamespace(create=create_response),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    answer = generator.generate_answer(
        "NASA was established in 1958.", "When was NASA founded?"
    )

    assert answer == "NASA was founded in 1958."
    assert "Context:\nNASA was established in 1958." in caplog.text
    assert "Question:\nWhen was NASA founded?" in caplog.text
    assert request["instructions"] == generator.GENERATION_INSTRUCTIONS


def test_generate_answer_wraps_api_failures(monkeypatch) -> None:
    def fail_request(**kwargs):
        raise RuntimeError("Generation API unavailable")

    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "responses",
                types.SimpleNamespace(create=fail_request),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    try:
        generator.generate_answer("NASA context", "What is NASA?")
    except generator.GenerationError as error:
        assert isinstance(error.__cause__, RuntimeError)
        assert str(error) == "Unable to generate an answer."
    else:
        raise AssertionError("Expected GenerationError for an API failure.")


def test_generate_answer_rejects_empty_model_output(monkeypatch) -> None:
    response = types.SimpleNamespace(output_text="   ")
    client = type(
        "Client",
        (),
        {
            "__init__": lambda self: setattr(
                self,
                "responses",
                types.SimpleNamespace(create=lambda **kwargs: response),
            )
        },
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=client))

    try:
        generator.generate_answer("NASA context", "What is NASA?")
    except generator.GenerationError as error:
        assert error.__cause__ is None
        assert str(error) == "The generation API returned an empty answer."
    else:
        raise AssertionError("Expected GenerationError for empty model output.")


def test_build_context_formats_retrieved_chunks() -> None:
    results = [
        DocumentChunk("hubble.txt", 0, "Hubble has five instruments.", [1.0]),
        DocumentChunk("iss.txt", 2, "The ISS supports research.", [1.0]),
    ]

    context = generator.build_context(results)

    assert context == (
        "[hubble.txt, chunk 0]\nHubble has five instruments.\n\n"
        "---\n\n[iss.txt, chunk 2]\nThe ISS supports research."
    )

    assert generator.build_chunk_references(results) == [
        "[hubble.txt, chunk 0]",
        "[iss.txt, chunk 2]",
    ]


def test_validate_answer_citations_appends_warning_for_invalid_citation() -> None:
    answer = generator.validate_answer_citations(
        "Hubble has five instruments. [hubble.txt, chunk 99]",
        ["[hubble.txt, chunk 0]"],
    )

    assert answer.endswith(
        "[Validation warning: citations not in retrieved chunks: "
        "[hubble.txt, chunk 99]]"
    )


def test_validate_answer_citations_keeps_valid_citation() -> None:
    answer = "Hubble has five instruments. [hubble.txt, chunk 0]"

    assert (
        generator.validate_answer_citations(answer, ["[hubble.txt, chunk 0]"])
        == answer
    )


def test_validate_answer_citations_keeps_answer_without_citations() -> None:
    answer = "Hubble has five instruments."

    assert (
        generator.validate_answer_citations(answer, ["[hubble.txt, chunk 0]"])
        == answer
    )


def test_generate_rag_answer_builds_context_before_generating(monkeypatch) -> None:
    results = [DocumentChunk("hubble.txt", 0, "Hubble has five instruments.", [1.0])]
    request = {}

    def generate_without_citation(context, question):
        request["context"] = context
        request["question"] = question
        return "Answer without citation."

    monkeypatch.setattr(
        semantic_search, "generate_answer", generate_without_citation
    )

    answer = semantic_search.generate_rag_answer("How many instruments?", results)

    assert request == {
        "context": "[hubble.txt, chunk 0]\nHubble has five instruments.",
        "question": "How many instruments?",
    }
    assert answer == "Answer without citation."


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


def test_create_index_rejects_invalid_embedding_matrices() -> None:
    invalid_matrices = [
        np.array([1.0, 2.0], dtype=np.float32),
        np.array([[0.0, 0.0]], dtype=np.float32),
        np.array([[np.nan, 1.0]], dtype=np.float32),
    ]

    for matrix in invalid_matrices:
        try:
            vector_store.create_index(matrix)
        except ValueError:
            continue
        raise AssertionError("Expected invalid embedding matrix to be rejected.")


def test_create_index_wraps_faiss_failures(monkeypatch) -> None:
    def fail_index_creation(_dimension):
        raise RuntimeError("FAISS unavailable")

    monkeypatch.setattr(vector_store.faiss, "IndexFlatIP", fail_index_creation)

    try:
        vector_store.create_index(np.array([[1.0, 0.0]], dtype=np.float32))
    except vector_store.VectorStoreError as error:
        assert isinstance(error.__cause__, RuntimeError)
        assert str(error) == "Unable to create FAISS index."
    else:
        raise AssertionError("Expected VectorStoreError for a FAISS failure.")


def test_validate_index_rejects_mismatched_chunk_metadata() -> None:
    index = vector_store.create_index(
        np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    )
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0, 0.0]),
        DocumentChunk("b.txt", 0, "second", [0.0, 1.0]),
    ]

    try:
        vector_store.validate_index(index, chunks)
    except vector_store.VectorStoreError as error:
        assert str(error) == "Index contains 3 vectors but metadata contains 2 chunks."
    else:
        raise AssertionError("Expected mismatched index metadata to be rejected.")


def test_create_query_matrix_normalizes_the_query_embedding() -> None:
    query_matrix = vector_store.create_query_matrix([3.0, 4.0])

    assert query_matrix.dtype == np.float32
    assert query_matrix.shape == (1, 2)
    assert np.allclose(query_matrix, [[0.6, 0.8]])
    assert np.allclose(np.linalg.norm(query_matrix, axis=1), [1.0])


def test_create_query_matrix_rejects_zero_and_nonfinite_vectors() -> None:
    for embedding in ([0.0, 0.0], [np.inf, 1.0]):
        try:
            vector_store.create_query_matrix(embedding)
        except ValueError:
            continue
        raise AssertionError("Expected invalid query embedding to be rejected.")


def test_faiss_retriever_returns_the_top_k_document_chunks(tmp_path) -> None:
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0, 0.0]),
        DocumentChunk("b.txt", 0, "second", [0.0, 1.0]),
    ]
    faiss_search = faiss_retriever.FaissRetriever(tmp_path / "document.index")
    faiss_search.load(chunks)

    ranked_chunks = faiss_search.search([1.0, 0.0], top_k=1)

    assert ranked_chunks == [chunks[0]]
    assert ranked_chunks[0].similarity == 1.0


def test_faiss_retriever_rejects_query_dimension_mismatch(tmp_path) -> None:
    faiss_search = faiss_retriever.FaissRetriever(tmp_path / "document.index")
    faiss_search.load([DocumentChunk("a.txt", 0, "first", [1.0, 0.0])])

    try:
        faiss_search.search([1.0, 0.0, 0.0], top_k=1)
    except ValueError as error:
        assert str(error) == "Query embedding dimension does not match the FAISS index."
    else:
        raise AssertionError("Expected query/index dimension mismatch to be rejected.")


def test_faiss_retriever_wraps_faiss_search_failures(monkeypatch, tmp_path) -> None:
    class BrokenIndex:
        d = 2
        ntotal = 1

        def search(self, query_matrix, top_k):
            raise RuntimeError("FAISS search failed")

    generic_retriever = retriever.Retriever(tmp_path)
    generic_retriever.faiss_retriever.document_chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0, 0.0])
    ]
    generic_retriever.faiss_retriever.index = BrokenIndex()
    monkeypatch.setattr(retriever, "embed_query", lambda _query: [1.0, 0.0])

    try:
        generic_retriever.search("find first", top_k=1)
    except retriever.RetrievalError as error:
        assert isinstance(error.__cause__, RuntimeError)
        assert str(error) == "Unable to search the FAISS index."
    else:
        raise AssertionError("Expected RetrievalError for a FAISS search failure.")


def test_faiss_retriever_wraps_load_failures(monkeypatch, tmp_path) -> None:
    def fail_load(*_args, **_kwargs):
        raise OSError("Cache unavailable")

    monkeypatch.setattr(retriever, "load_and_embed_directory", fail_load)

    try:
        retriever.Retriever(tmp_path).load()
    except retriever.RetrievalError as error:
        assert isinstance(error.__cause__, OSError)
        assert str(error) == "Unable to load the retriever."
    else:
        raise AssertionError("Expected RetrievalError for a load failure.")


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
