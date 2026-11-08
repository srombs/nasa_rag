# NASA RAG

Language for searching NASA documents and explaining how an answer was produced.

## Language

**Search flow**:
The ordered stages and intermediate results used to produce an answer to one
visitor question, including the progress and outcome of those stages.
_Avoid_: Raw logs (when referring to the visitor-facing search flow)

**Retrieved passage**:
A document chunk selected by retrieval as a candidate for answering a question.
Its selection does not establish that the answer cites it or that it proves a
claim.
_Avoid_: Verified source

**Citation reference check**:
A check that citation references appearing in an answer name passages supplied
as retrieved context. It does not check the factual accuracy of the answer.
_Avoid_: Fact check
