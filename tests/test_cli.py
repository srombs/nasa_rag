import json
import logging
import sys
import types

import embedder
import bm25_retriever
import faiss_retriever
import file_loader
import generator
import chunkers
import numpy as np
import retriever
import reranker
import query_rewriter
import semantic_search
import tokenizer
import vector_store
from models import (
    BM25SearchResult,
    DocumentChunk,
    HybridSearchResult,
    RerankResult,
    TokenizedChunk,
)

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


def test_tokenize_text_returns_all_words_and_preserves_duplicates() -> None:
    assert tokenizer.tokenize_text("What is the power of the ISS, ISS?") == [
        "what",
        "is",
        "the",
        "power",
        "of",
        "the",
        "iss",
        "iss",
    ]


def test_tokenize_text_excluding_stop_words_preserves_duplicates() -> None:
    assert tokenizer.tokenize_text_excluding_stop_words(
        "What is the power of the ISS, ISS?"
    ) == [
        "power",
        "iss",
        "iss",
    ]


def test_tokenize_text_set_removes_duplicate_non_stop_words() -> None:
    assert tokenizer.tokenize_text_set("The ISS is in orbit, orbit!") == {
        "iss",
        "orbit",
    }


def test_bm25_retriever_tokenizes_every_document_chunk_word() -> None:
    chunks = [DocumentChunk("iss.txt", 0, "The ISS is in orbit.", [1.0])]
    bm25 = bm25_retriever.BM25Retriever()

    bm25.load(chunks)

    assert bm25.document_chunks == chunks
    assert bm25.tokenized_documents == [["the", "iss", "is", "in", "orbit"]]
    assert bm25.index is not None


def test_bm25_retriever_scores_a_tokenized_query() -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS orbit research.", [1.0]),
        DocumentChunk("hubble.txt", 1, "Hubble telescope.", [1.0]),
        DocumentChunk("mars.txt", 2, "Mars rover mission.", [1.0]),
    ]
    bm25 = bm25_retriever.BM25Retriever()
    bm25.load(chunks)

    results = bm25.search(["iss", "research"], top_k=1)

    assert results[0].chunk == chunks[0]
    assert results[0].score > 0


def test_bm25_retriever_filters_results_by_source_file() -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS orbit research.", [1.0]),
        DocumentChunk("hubble.txt", 1, "ISS telescope research.", [1.0]),
        DocumentChunk("iss.txt", 2, "ISS crew research.", [1.0]),
    ]
    bm25 = bm25_retriever.BM25Retriever()
    bm25.load(chunks)

    results = bm25.search(
        ["iss", "research"], top_k=2, source_file_filter="iss.txt"
    )

    assert [result.chunk for result in results] == [chunks[0], chunks[2]]


def test_bm25_retriever_returns_no_results_when_source_file_does_not_match() -> None:
    chunks = [DocumentChunk("iss.txt", 0, "ISS orbit research.", [1.0])]
    bm25 = bm25_retriever.BM25Retriever()
    bm25.load(chunks)

    assert bm25.search(["iss"], top_k=1, source_file_filter="hubble.txt") == []


def test_faiss_source_filter_doubles_the_candidate_count(tmp_path) -> None:
    chunks = [
        DocumentChunk("hubble.txt", 0, "Hubble.", [1.0, 0.0]),
        DocumentChunk("iss.txt", 1, "ISS power.", [0.9, 0.1]),
        DocumentChunk("hubble.txt", 2, "Telescope.", [0.8, 0.2]),
        DocumentChunk("iss.txt", 3, "ISS crew.", [0.7, 0.3]),
    ]
    received = {}

    class SearchIndex:
        d = 2
        ntotal = len(chunks)

        def search(self, _query_matrix, top_k):
            received["top_k"] = top_k
            return (
                np.array([[1.0, 0.9, 0.8, 0.7]], dtype=np.float32),
                np.array([[0, 1, 2, 3]], dtype=np.int64),
            )

    faiss_search = faiss_retriever.FaissRetriever(tmp_path / "document.index")
    faiss_search.document_chunks = chunks
    faiss_search.index = SearchIndex()

    results = faiss_search.search(
        [1.0, 0.0], top_k=2, source_file_filter="iss.txt"
    )

    assert received["top_k"] == 4
    assert results == [chunks[1], chunks[3]]


def test_score_tokenized_chunks_ranks_normalized_keyword_overlap() -> None:
    chunks = [
        TokenizedChunk("iss.txt", 0, {"iss", "crew", "research"}),
        TokenizedChunk("hubble.txt", 1, {"hubble", "telescope"}),
    ]

    scores = tokenizer.score_tokenized_chunks(
        tokenizer.tokenize_text_set("ISS research telescope"), chunks
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
    assert generic_retriever.bm25_retriever.index is not None


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


def test_retriever_search_bm25_tokenizes_the_query(monkeypatch, tmp_path) -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS orbit research.", [1.0, 0.0]),
        DocumentChunk("hubble.txt", 1, "Hubble telescope.", [0.0, 1.0]),
        DocumentChunk("mars.txt", 2, "Mars rover mission.", [0.5, 0.5]),
    ]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )
    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()
    monkeypatch.setattr(generic_retriever.query_rewriter, "rewrite", lambda query: query)

    results = generic_retriever.search_bm25("What ISS research?", top_k=1)

    assert results[0].chunk == chunks[0]
    assert results[0].score > 0


def test_retriever_search_bm25_passes_every_query_word(monkeypatch, tmp_path) -> None:
    chunks = [DocumentChunk("iss.txt", 0, "ISS orbit research.", [1.0, 0.0])]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )
    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()
    received = {}

    def capture_search(tokens, top_k, source_file_filter=None):
        received["tokens"] = tokens
        received["top_k"] = top_k
        received["source_file_filter"] = source_file_filter
        return []

    monkeypatch.setattr(generic_retriever.bm25_retriever, "search", capture_search)
    monkeypatch.setattr(
        generic_retriever.query_rewriter,
        "rewrite",
        lambda _query: "ISS electrical power",
    )

    generic_retriever.search_bm25(
        "What is the ISS?", top_k=1, source_file_filter="iss.txt"
    )

    assert received == {
        "tokens": ["iss", "electrical", "power"],
        "top_k": 1,
        "source_file_filter": "iss.txt",
    }


def test_retriever_search_rrf_fuses_faiss_and_bm25_rankings(monkeypatch, tmp_path) -> None:
    chunks = [
        DocumentChunk("a.txt", 0, "first", [1.0, 0.0]),
        DocumentChunk("b.txt", 1, "second", [0.0, 1.0]),
        DocumentChunk("c.txt", 2, "third", [0.5, 0.5]),
    ]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )
    monkeypatch.setattr(retriever, "embed_query", lambda _query: [1.0, 0.0])
    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()
    monkeypatch.setattr(generic_retriever.query_rewriter, "rewrite", lambda query: query)
    monkeypatch.setattr(
        generic_retriever.faiss_retriever,
        "search",
        lambda _embedding, top_k, source_file_filter=None: chunks[:top_k],
    )
    monkeypatch.setattr(
        generic_retriever.bm25_retriever,
        "search",
        lambda _tokens, top_k, source_file_filter=None: [
            BM25SearchResult(1.0, chunks[1]),
            BM25SearchResult(1.0, chunks[2]),
            BM25SearchResult(1.0, chunks[0]),
        ][:top_k],
    )

    results = generic_retriever.search_rrf("ISS research", top_k=3, rrf_k=1)

    assert results == [chunks[1], chunks[0], chunks[2]]
    assert round(chunks[0].rrf_score, 4) == 0.75
    assert round(chunks[1].rrf_score, 4) == 0.8333
    assert round(chunks[2].rrf_score, 4) == 0.5833
    assert (chunks[0].faiss_rank, chunks[0].bm25_rank) == (1, 3)
    assert (chunks[1].faiss_rank, chunks[1].bm25_rank) == (2, 1)
    assert (chunks[2].faiss_rank, chunks[2].bm25_rank) == (3, 2)


def test_retriever_uses_rewritten_query_for_rrf_and_original_query_for_reranking(
    monkeypatch, tmp_path
) -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS power.", [1.0, 0.0]),
        DocumentChunk("iss.txt", 1, "ISS crew.", [0.0, 1.0]),
    ]
    generic_retriever = retriever.Retriever(tmp_path)
    generic_retriever.document_chunks = chunks
    received = {}

    def rewrite(query):
        received["rewrite_query"] = query
        return "ISS electrical power"

    def embed(query):
        received["faiss_query"] = query
        return [1.0, 0.0]

    def bm25_search(tokens, top_k, source_file_filter=None):
        received["bm25_tokens"] = tokens
        received["bm25_source_file_filter"] = source_file_filter
        return [BM25SearchResult(1.0, chunk) for chunk in chunks[:top_k]]

    def rerank(original_query, rrf_results):
        received["rerank_query"] = original_query
        return [RerankResult(rrf_results[0], 1.0, "Directly relevant.")]

    monkeypatch.setattr(generic_retriever.query_rewriter, "rewrite", rewrite)
    monkeypatch.setattr(retriever, "embed_query", embed)
    monkeypatch.setattr(
        generic_retriever.faiss_retriever,
        "search",
        lambda _embedding, top_k, source_file_filter=None: chunks[:top_k],
    )
    monkeypatch.setattr(generic_retriever.bm25_retriever, "search", bm25_search)
    monkeypatch.setattr(generic_retriever, "rerank_rrf_results", rerank)

    results = generic_retriever.search_faiss_bm25_rrf_and_rerank(
        "What powers the ISS?", top_k=2, rrf_top_k=2
    )

    assert received == {
        "rewrite_query": "What powers the ISS?",
        "faiss_query": "ISS electrical power",
        "bm25_tokens": ["iss", "electrical", "power"],
        "bm25_source_file_filter": None,
        "rerank_query": "What powers the ISS?",
    }
    assert results[-1] == "ISS electrical power"


def test_reranker_reranks_rrf_results_with_model_scores_and_reasons() -> None:
    rrf_results = [
        DocumentChunk("iss.txt", 0, "ISS power systems.", [1.0], rrf_score=0.02),
        DocumentChunk("hubble.txt", 1, "Hubble telescope.", [1.0], rrf_score=0.03),
    ]

    requests = []

    def create_response(**kwargs):
        requests.append(kwargs)
        output_text = (
            '{"score": 1.0, "reason": "The chunk directly discusses ISS power."}'
            if "ISS power systems." in kwargs["input"]
            else '{"score": 0.0, "reason": "The chunk is about Hubble."}'
        )
        return types.SimpleNamespace(output_text=output_text)

    client = types.SimpleNamespace(
        responses=types.SimpleNamespace(create=create_response)
    )
    results = reranker.Reranker(client=client).rerank("ISS power", rrf_results)

    assert results == [
        RerankResult(
            chunk=rrf_results[0],
            score=1.0,
            reason="The chunk directly discusses ISS power.",
        ),
        RerankResult(
            chunk=rrf_results[1],
            score=0.0,
            reason="The chunk is about Hubble.",
        ),
    ]
    assert len(requests) == 2
    assert requests[0]["model"] == reranker.RERANK_MODEL
    assert requests[0]["instructions"] == reranker.RERANK_INSTRUCTIONS
    assert requests[0]["input"] == "Query:\nISS power\n\nChunk:\nISS power systems."


def test_query_rewriter_sends_the_user_query_to_the_model() -> None:
    request = {}

    def create_response(**kwargs):
        request.update(kwargs)
        return types.SimpleNamespace(output_text="ISS electrical power system")

    client = types.SimpleNamespace(
        responses=types.SimpleNamespace(create=create_response)
    )
    rewriter = query_rewriter.QueryRewriter(client=client)

    rewritten_query = rewriter.rewrite("What powers the ISS?")

    assert rewritten_query == "ISS electrical power system"
    assert request == {
        "model": query_rewriter.QUERY_REWRITE_MODEL,
        "instructions": query_rewriter.QUERY_REWRITE_INSTRUCTIONS,
        "input": "What powers the ISS?",
    }


def test_query_rewriter_rejects_empty_query() -> None:
    rewriter = query_rewriter.QueryRewriter()
    try:
        rewriter.rewrite("   ")
    except ValueError as error:
        assert str(error) == "Query text cannot be empty."
    else:
        raise AssertionError("Expected an empty query to be rejected.")


def test_retriever_delegates_rrf_results_to_the_reranker(monkeypatch, tmp_path) -> None:
    generic_retriever = retriever.Retriever(tmp_path)
    rrf_results = [DocumentChunk("iss.txt", 0, "ISS power.", [1.0])]
    expected = [RerankResult(rrf_results[0], 1.0, "Matched query tokens: iss.")]
    monkeypatch.setattr(generic_retriever.reranker, "rerank", lambda *_args: expected)

    assert generic_retriever.rerank_rrf_results("ISS", rrf_results) == expected


def test_retriever_reranks_after_building_rrf_results(monkeypatch, tmp_path) -> None:
    generic_retriever = retriever.Retriever(tmp_path)
    faiss_results = [DocumentChunk("iss.txt", 0, "FAISS", [1.0])]
    bm25_results = [BM25SearchResult(1.0, DocumentChunk("iss.txt", 1, "BM25", [1.0]))]
    rrf_results = [DocumentChunk("iss.txt", 2, "RRF", [1.0])]
    rerank_results = [RerankResult(rrf_results[0], 1.0, "Directly relevant.")]
    monkeypatch.setattr(
        generic_retriever,
        "search_faiss_bm25_and_rrf",
        lambda *_args, **_kwargs: (faiss_results, bm25_results, rrf_results),
    )
    monkeypatch.setattr(
        generic_retriever.query_rewriter, "rewrite", lambda _query: "rewritten ISS"
    )
    monkeypatch.setattr(
        generic_retriever,
        "rerank_rrf_results",
        lambda _query, results: rerank_results if results == rrf_results else [],
    )

    results = generic_retriever.search_faiss_bm25_rrf_and_rerank(
        "ISS", top_k=1
    )

    assert results == (
        faiss_results,
        bm25_results,
        rrf_results,
        rerank_results,
        "rewritten ISS",
    )


def test_retriever_search_hybrid_combines_semantic_and_keyword_scores(
    monkeypatch, tmp_path
) -> None:
    chunks = [
        DocumentChunk("iss.txt", 0, "ISS crew research.", [1.0, 0.0]),
        DocumentChunk("hubble.txt", 1, "Hubble telescope.", [0.0, 1.0]),
    ]
    monkeypatch.setattr(
        retriever, "load_and_embed_directory", lambda *_args, **_kwargs: chunks
    )
    monkeypatch.setattr(retriever, "embed_query", lambda _query: [1.0, 0.0])
    generic_retriever = retriever.Retriever(
        tmp_path, cache_directory=tmp_path / "cache"
    )
    generic_retriever.load()
    monkeypatch.setattr(generic_retriever.query_rewriter, "rewrite", lambda query: query)

    semantic_results, results = generic_retriever.search_semantic_and_hybrid(
        "ISS telescope", top_k=2, semantic_weight=0.7, keyword_weight=0.3
    )

    assert semantic_results == chunks
    assert [result.document_chunk for result in results] == chunks
    assert results[0].semantic_score == 1.0
    assert results[0].keyword_score == 0.5
    assert results[0].hybrid_score == 0.85
    assert results[1].hybrid_score == 0.15


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

    assert capsys.readouterr().out == "0.9000 | [a.txt, chunk 0]\n"


def test_run_keyword_search_delegates_to_the_retriever() -> None:
    class KeywordRetriever:
        def search_keywords(self, query, top_k):
            assert query == "ISS research"
            assert top_k == 2
            return [DocumentChunk("iss.txt", 0, "ISS research.", [1.0])]

    results = semantic_search.run_keyword_search(
        "ISS research", KeywordRetriever(), top_k=2
    )

    assert [(result.source, result.chunk_index) for result in results] == [
        ("iss.txt", 0)
    ]


def test_run_bm25_search_delegates_to_the_retriever() -> None:
    class BM25Retriever:
        def search_bm25(self, query, top_k, source_file_filter):
            assert query == "ISS research"
            assert top_k == 2
            assert source_file_filter == "iss.txt"
            return [
                BM25SearchResult(
                    score=1.0,
                    chunk=DocumentChunk("iss.txt", 0, "ISS research.", [1.0]),
                )
            ]

    results = semantic_search.run_bm25_search(
        "ISS research", BM25Retriever(), top_k=2, source_file_filter="iss.txt"
    )

    assert [(result.chunk.source, result.chunk.chunk_index) for result in results] == [
        ("iss.txt", 0)
    ]


def test_print_bm25_results_uses_the_result_object(capsys) -> None:
    results = [
        BM25SearchResult(
            score=2.5,
            chunk=DocumentChunk("iss.txt", 0, "ISS research.", [1.0]),
        )
    ]

    semantic_search.print_bm25_results(results)

    assert capsys.readouterr().out == "2.5000 | [iss.txt, chunk 0]\n"


def test_print_rrf_results_includes_source_rankings(capsys) -> None:
    chunk = DocumentChunk(
        "iss.txt",
        0,
        "ISS research.",
        [1.0],
        rrf_score=0.03,
        faiss_rank=1,
        bm25_rank=2,
    )

    semantic_search.print_rrf_results([chunk])

    assert capsys.readouterr().out == (
        "rrf 0.0300 | FAISS rank 1 | BM25 rank 2 | "
        "[iss.txt, chunk 0]\n"
    )


def test_print_rerank_results_includes_model_score_and_reason(capsys) -> None:
    results = [
        RerankResult(
            DocumentChunk("iss.txt", 0, "ISS research.", [1.0]),
            score=0.9,
            reason="The chunk directly answers the query.",
        )
    ]

    semantic_search.print_rerank_results(results)

    assert capsys.readouterr().out == (
        "rerank 0.9000 | [iss.txt, chunk 0] | "
        "The chunk directly answers the query.\n"
    )


def test_run_both_searches_returns_independent_rankings() -> None:
    class SearchRetriever:
        def search_faiss_bm25_rrf_and_rerank(
            self, query, top_k, rrf_top_k, source_file_filter
        ):
            assert (query, top_k) == ("ISS research", 2)
            assert rrf_top_k == semantic_search.RRF_TOP_K
            assert source_file_filter is None
            return [DocumentChunk("iss.txt", 0, "semantic", [1.0])], [
                BM25SearchResult(
                    score=1.0, chunk=DocumentChunk("iss.txt", 1, "bm25", [1.0])
                )
            ], [
                DocumentChunk("iss.txt", 2, "rrf", [1.0], rrf_score=0.03)
            ], [
                RerankResult(
                    DocumentChunk("iss.txt", 3, "reranked", [1.0]),
                    score=1.0,
                    reason="Directly relevant.",
                )
            ], "ISS research rewritten"

    faiss_results, bm25_results, rrf_results, rerank_results, rewritten_query = (
        semantic_search.run_both_searches("ISS research", SearchRetriever(), top_k=2)
    )

    assert faiss_results[0].text == "semantic"
    assert bm25_results[0].chunk.text == "bm25"
    assert rrf_results[0].text == "rrf"
    assert rerank_results[0].chunk.text == "reranked"
    assert rewritten_query == "ISS research rewritten"


def test_both_searches_prints_original_and_rewritten_queries(monkeypatch, capsys) -> None:
    monkeypatch.setattr(semantic_search, "load_retriever", lambda *_args: object())
    monkeypatch.setattr(
        semantic_search,
        "run_both_searches",
        lambda *_args, **_kwargs: ([], [], [], [], "ISS electrical power"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["semantic_search.py", "What powers the ISS?", "--both-searches"],
    )

    semantic_search.main()

    output = capsys.readouterr().out
    assert "Original query:\nWhat powers the ISS?" in output
    assert "Rewritten query:\nISS electrical power" in output
    assert output.index("Original query:") < output.index("Rewritten query:")
    assert output.index("Rewritten query:") < output.index("FAISS results:")
    assert output.index("FAISS results:") < output.index("BM25 results:")
    assert output.index("BM25 results:") < output.index("RRF results:")
    assert output.index("RRF results:") < output.index("Reranked results:")


def test_run_hybrid_search_delegates_weights_to_the_retriever() -> None:
    class HybridRetriever:
        def search_hybrid(self, query, top_k, semantic_weight, keyword_weight):
            assert (query, top_k) == ("ISS research", 2)
            assert (semantic_weight, keyword_weight) == (0.8, 0.2)
            return [
                HybridSearchResult(
                    DocumentChunk("iss.txt", 0, "hybrid", [1.0]),
                    semantic_score=1.0,
                    keyword_score=1.0,
                    hybrid_score=1.0,
                )
            ]

    results = semantic_search.run_hybrid_search(
        "ISS research",
        HybridRetriever(),
        top_k=2,
        semantic_weight=0.8,
        keyword_weight=0.2,
    )

    assert results[0].document_chunk.text == "hybrid"


def test_run_semantic_and_hybrid_search_delegates_to_the_retriever() -> None:
    semantic_result = DocumentChunk("iss.txt", 0, "semantic", [1.0])
    hybrid_result = HybridSearchResult(
        DocumentChunk("iss.txt", 0, "hybrid", [1.0]),
        semantic_score=1.0,
        keyword_score=1.0,
        hybrid_score=1.0,
    )

    class HybridRetriever:
        def search_semantic_and_hybrid(
            self, query, top_k, semantic_weight, keyword_weight
        ):
            assert (query, top_k) == ("ISS research", 2)
            assert (semantic_weight, keyword_weight) == (0.8, 0.2)
            return [semantic_result], [hybrid_result]

    semantic_results, hybrid_results = semantic_search.run_semantic_and_hybrid_search(
        "ISS research",
        HybridRetriever(),
        top_k=2,
        semantic_weight=0.8,
        keyword_weight=0.2,
    )

    assert semantic_results == [semantic_result]
    assert hybrid_results == [hybrid_result]


def test_print_hybrid_results_includes_all_scores(capsys) -> None:
    results = [
        HybridSearchResult(
            DocumentChunk("iss.txt", 0, "ISS research.", [1.0]),
            semantic_score=0.8,
            keyword_score=0.5,
            hybrid_score=0.71,
        )
    ]

    semantic_search.print_hybrid_results(results)

    assert capsys.readouterr().out == (
        "hybrid 0.7100 | semantic 0.8000 | keyword 0.5000 | "
        "[iss.txt, chunk 0]\n"
    )


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
    monkeypatch.setattr(generic_retriever.query_rewriter, "rewrite", lambda query: query)

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
