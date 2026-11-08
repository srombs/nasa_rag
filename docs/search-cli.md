# Search CLI and logging reference

Recorded on 2026-11-06 from the current implementation. This guide covers the
regular search CLI; evaluation runners have their own arguments.

Both entry points run the same CLI and accept the same arguments:

```sh
uv run nasa-rag "What powers the ISS?" --generate-answer
uv run python semantic_search.py "What powers the ISS?" --generate-answer
```

## Default search behavior

A plain search loads the corpus and indexes, rewrites the question with a model,
embeds the rewritten query, and searches FAISS. It prints the original question
and matching chunk scores and references. It does not generate an answer unless
`--generate-answer` is supplied.

`--both-searches` runs retrieval planning, FAISS and BM25 search, reciprocal rank
fusion (RRF), and model reranking. The planner supplies the rewritten search query
and an optional source restriction. Reranking and answer generation use the
original question.

## CLI arguments

| Argument | Default | Behavior |
| --- | --- | --- |
| `query` | Required | Question or search phrase. Quote it when it contains spaces. |
| `--chunk-size N` | `100` | Words per document chunk. Must be greater than zero. Changing it selects separate embedding and index caches and may trigger document embedding requests. |
| `--overlap-size N` | `20` | Words shared between adjacent chunks. Must be nonnegative and smaller than chunk size. Also affects cache selection. |
| `--top-k N` | `30` | Number of returned FAISS or BM25 results. In hybrid mode, controls those two printed lists; fusion and reranking still use ten candidates. |
| `--generate-answer` | Off | Generates an answer using the original question and retrieved chunks. Hybrid mode uses the reranked chunks. |
| `--bm25-search` | Off | Uses keyword-based BM25 instead of FAISS. Skips query embedding, but still calls the query rewriter. Shared startup can still embed uncached documents. |
| `--both-searches` | Off | Runs retrieval planning, FAISS, BM25, RRF, and model reranking. Prints every ranking. Add `--generate-answer` to generate an answer too. |
| `--source-file NAME` | All sources | Restricts results to a loaded filename such as `iss.txt`. Overrides the planner's source filter in hybrid mode. Does not restrict initial corpus loading. |
| `-h`, `--help` | — | Prints help and exits without running a search. |

`--bm25-search` and `--both-searches` are mutually exclusive. There are no CLI
arguments for selecting the model, changing the ten RRF candidates, or disabling
query rewriting/planning.

In hybrid mode, fusion uses the full eligible FAISS and BM25 rankings before
selecting ten candidates; `--top-k` only limits the two printed base rankings.
The CLI uses RRF constant `60`.

## Examples

Retrieve the top three FAISS matches:

```sh
uv run nasa-rag "What powers the ISS?" --top-k 3
```

Generate an answer from FAISS results:

```sh
uv run nasa-rag "What powers the ISS?" --generate-answer
```

Use BM25 with a source restriction:

```sh
uv run nasa-rag "What powers the ISS?" --bm25-search --source-file iss.txt
```

Run the full hybrid pipeline and generate an answer:

```sh
uv run nasa-rag "What powers the ISS?" \
  --both-searches \
  --generate-answer \
  --source-file iss.txt
```

## Console logging and printed output

| Output | Contents | Destination |
| --- | --- | --- |
| Operational logs | `INFO` and higher, formatted as `LEVEL \| module \| message`, without timestamps. | stderr |
| Search results | Original question, result scores, and `[source.txt, chunk N]` references; optional generated answer. | stdout |
| Model cost summary | Run ID, call counts and known estimated cost by operation, known total, and unknown-cost call counts. | stdout |

Pipeline events appear as follows:

- **Document loading:** when embeddings are missing, prints the number of chunks
  created and logs the source filename and number sent for embedding. Cached
  documents make no embedding request.
- **FAISS index:** logs loading, writing, or rebuilding its cache; warns about
  unreadable cache files.
- **Query rewriting:** logs the original query sent to the model and receipt of
  the response. The default mode does not print the rewritten query.
- **Hybrid search:** logs the planner's input and returned plan, plus request and
  response messages identifying each reranked source/chunk. Prints the rewritten
  query, effective source filter, FAISS and BM25 scores, RRF scores and source
  ranks, and reranking scores and reasons.
- **Answer generation:** logs the full retrieved context and original question
  sent to the model, then receipt of the response. Prints the answer separately.
  Unrecognized chunk citations cause a validation warning to be appended to the
  answer.
- **Failures:** embedding, rewriting, planning, reranking, generation, and certain
  index failures log exceptions with tracebacks. Not every validation failure has
  its own logging statement.

The cost summary prints at the end of the run, including failed runs. A normal
`--help` exit does not print a summary.

There are no `--verbose`, `--debug`, `--quiet`, `--log-level`, or `--log-file`
arguments. The CLI has no built-in timing breakdown and does not configure a file
handler for operational logs. Terminal output can contain questions, retrieved
document text, and answers.

## Persistent model cost ledger

Each application call through `call_model` appends one JSON object to the JSONL
ledger. This covers document embedding, query embedding, query rewriting,
retrieval planning, reranking, and answer generation when those operations run.
Internal provider-client retry attempts are not separate ledger records.

Default locations:

- Source checkout: `logs/model_costs.jsonl` under the repository root.
- Installed outside the checkout: `~/.local/state/nasa_rag/model_costs.jsonl`.

Set `NASA_RAG_COST_LOG_PATH` to choose another location:

```sh
NASA_RAG_COST_LOG_PATH=/tmp/nasa-rag-costs.jsonl \
  uv run nasa-rag "What powers the ISS?" --generate-answer
```

Each record includes:

- UTC timestamp, run ID, and run name (`search` for CLI runs).
- Operation, endpoint, requested model, and response model when available.
- Status (`response` or `error`) and exception type when applicable.
- Available token counts, including cached input, cache-write, output, and
  reasoning tokens for Responses calls.
- Estimated USD cost, configured token rates, and the rate date.

The ledger does not store prompts, retrieved text, or model outputs. Missing or
incomplete usage, unknown pricing, and failed requests produce an unknown cost
instead of a zero-cost estimate. Cached document embeddings create no new model
call or cost record. Estimates use rates in `model_costs.py` and can differ from
actual billing.

A successful API response is recorded before application-level output validation,
so a later malformed-output failure can still have ledger status `response`.
Ledger write failures log a warning with a traceback and do not abort the search.

## Difference from the web API

The deployed `/ask` endpoint always uses the full hybrid answer pipeline. During
the web lifespan, it suppresses the detailed RAG and provider HTTP logs and emits
a request record containing request ID, HTTP status, and elapsed milliseconds.

Cost records still write, but currently share the process-level `unscoped` run
rather than a distinct run per HTTP request. They are not correlated with the
HTTP request ID, and the web pipeline does not print a CLI cost summary. See the
[web API guide](web-api.md#errors-and-logs) for HTTP logging behavior.

## Implementation references

- [CLI arguments, output, and orchestration](../src/nasa_rag/search.py)
- [Retrieval modes and defaults](../src/nasa_rag/retrieval/retriever.py)
- [Cost recording and summaries](../src/nasa_rag/model_costs.py)
- [Default cache and ledger paths](../src/nasa_rag/paths.py)
- [Embedding logging](../src/nasa_rag/embedder.py)
- [Generation logging and citation validation](../src/nasa_rag/generation/generator.py)
- [Web logging and request records](../src/nasa_rag/web.py)
