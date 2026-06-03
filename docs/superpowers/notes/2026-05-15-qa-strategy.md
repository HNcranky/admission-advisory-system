# Q&A Strategy Note - V1 Scope Decision and Future RAG Slice

**Date:** 2026-05-15
**Status:** Accepted - informs the conflict-aware advisory V1 and all downstream specs

---

## Scope Decision for V1

The conflict-aware advisory V1 answers **profile-driven recommendation questions**
("which programs fit my profile?"). Those questions are served by structured SQL
retrieval over `canonical_admission_records` - implemented at
`services/retrieval_service.py:fetch_candidates`. **The database is ready for those
queries.** The conflict-aware spec adds field-level conflict resolution on top; it
does not change the retrieval shape.

The database is **not ready** for open-ended student Q&A such as:
- "What scholarships does HUST offer?"
- "What's the early-admission deadline at UET?"
- "Does program X accept high-school olympiad winners?"

The answers to those questions live in the source text body, captured in
`raw_documents.parsed_text` but not semantically indexed. Open-ended Q&A is
**deferred to a separate post-V1 spec**.

---

## Why the Deferral Is Safe

- The advisory agent and the future Q&A agent serve different intents. Routing
  student input to one or the other is a chat-layer concern, not a graph-layer
  concern. The conflict-aware advisory graph stays as-is; the Q&A agent will be a
  separate graph or chain.
- `raw_documents.parsed_text` is already populated for every fetched source. The
  future RAG slice has its raw material ready - no re-fetching needed.
- Conflict resolution in V1 is field-level (quota mismatch between two sources).
  Narrative-passage conflicts (two source texts saying different things about
  scholarships) are a different problem with different resolution semantics. The V1
  design does not have to cover that case.

---

## Future RAG Slice - Touch Points to Preserve

These are the lines V1 must not violate. Future readers use this list to know which
design decisions are load-bearing:

| What to keep | Why |
|---|---|
| `raw_documents.parsed_text` populated | Future RAG slice reads it for chunking |
| `raw_documents.fetched_at` populated | Recency signal for embedding-refresh logic |
| `raw_documents.source_id` joinable to `source_registry` | Authority and trust signals carry into RAG ranking |
| Table name `document_chunks` unused | Reserved for the future chunking table |
| Retrieval layer as a thin function call | Don't bake "only SQL surface" assumptions into shared code |

### What the future RAG slice will introduce (new, no existing schema disturbed)

- A `document_chunks` table: `(id, raw_document_id, chunk_index, body_text, embedding vector(N), char_start, char_end, ...)`
- A chunking + embedding pipeline stage that reads `raw_documents` and writes `document_chunks`
- A `qa_agent` that issues semantic retrieval queries against `document_chunks`
- A chat-layer intent classifier that routes input to either `advisory_agent` or `qa_agent`

---

## What NOT to Do in V1

- Don't drop `raw_documents.parsed_text` or move it to cold storage.
- Don't make `raw_documents.source_id` non-joinable to `source_registry`.
- Don't reuse the table name `document_chunks` for anything else.
- Don't bake the assumption "the only retrieval surface is `canonical_admission_records`"
  into shared library code.

---

## Open Question Deferred to the Future Q&A Spec

Conflict resolution semantics for narrative passages: two source texts saying
contradictory things about a scholarship policy. The structured-conflict resolution
layer (Evidence/Comparison/Resolution) cannot directly apply because passage-level
disagreement is not field-level. The future Q&A spec must propose its own resolution
shape - likely: surface both passages with provenance, let the LLM compose a hedged
answer, never declare one passage "winning."
