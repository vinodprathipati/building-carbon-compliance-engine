# AI transcript — table-extraction chunking strategy

Session continuing from `04-regulation-pipeline-chunking-embedding.md`. Goal:
design and implement a second, table-focused chunking strategy alongside the
existing general one, after empirically finding the general strategy's
retrieval quality breaks down on tables.

---

**User:** shared a reference implementation from another project
(`cat-deal-extractor/.../docling_chunker.py`) with two strategies — `block`
(one chunk per item/table row) and `section` (group by section header) —
noting it also breaks tables down and prepends section-header context to
keep chunks context-aware.

**Assistant:** Compared it to our approach. Confirmed the "context-aware
chunk" property is already covered here via `chunker.contextualize()`. Flagged
the reference project's `section` strategy has the same weakness diagnosed
earlier on RCNY (no token-budget splitting, breaks on a single-top-level-
header document). Initially recommended adopting per-row table chunking for
retrieval precision.

**User:** pushed back — their use case is selective retrieval (only some rows
matter), ours extracts every row regardless, so why would row-level chunking
help?

**Assistant:** Conceded the retrieval-precision justification didn't apply.
Reframed toward a different question: since Docling already gives structured
`table.data.grid`, why route table data through an LLM at all instead of
parsing it deterministically in code?

**User:** raised the real problem this doesn't solve: a PDF may have many
tables (RCNY has 26), format varies by municipality, and there's no way to
know *which* table is the target ahead of time without hardcoding per-city
page numbers.

**Assistant:** Agreed this reframes it as a retrieval/identification problem,
not a parsing problem. Proposed: retrieve candidates via embedding search,
have an LLM confirm which table, then parse that table's grid deterministically
once identified.

**User:** asked for a concrete example.

**Assistant:** Ran a live retrieval test against the real stored embeddings
(`rag_id = 6`, 39 chunks from the general strategy). Query: "table of
greenhouse gas emissions factors by property type and compliance period."
Result: the chunk actually containing three of the four target tables
(chunk 21, pages 38-46, 20,009 characters) ranked **#11 of 39** — behind
unrelated penalty text and narrative preamble. Diagnosis: one chunk mixing
five+ topics under RCNY's single top-level section header produces a blurry,
diluted embedding. Proposed small-to-big retrieval (small chunks for search,
wider context for extraction) as the standard fix.

**User:** proposed a sharper version — for each table, don't embed the full
table at all; instead embed a small "descriptor" (context + column headers +
a reference to the table), semantic-search finds the descriptor, LLM confirms
the table reference, then pull the full table content separately.

**Assistant:** Validated this as strictly better than the small-to-big idea —
it removes the dilution cause entirely rather than just narrowing candidates.
Flagged the one real implementation gap: `HybridChunker` doesn't isolate
tables cleanly (it merged three into one chunk on RCNY), so this needs a
custom document traversal independent of `HybridChunker`.

**User:** asked where the actual table data should live — separate table?
`chunk_meta`? Raw text?

**Assistant:** Recommended a dedicated `document_tables` table (not
`chunk_meta`, not raw flattened text): `rows` as JSONB objects keyed by
column header (self-describing, directly consumable by deterministic
extraction code), linked to its descriptor chunk via `chunk_id`.

**User:** proposed running both strategies (general + table-extraction) as
parallel passes, framing table-extraction as potentially useful for other
use cases (e.g. a chat UI) beyond structured extraction.

**Assistant:** Initially proposed a `strategy` column + relaxing the
`rag_documents_one_active_per_key` constraint to `UNIQUE (document_key,
strategy)`, assuming each strategy needed its own `rag_documents` row.

**User:** corrected this — one `rag_documents` row per document; both
strategies populate their respective tables (`document_chunks` /
`document_tables`) against the same `rag_id`. No need for two rows.

**Assistant:** Agreed — this dissolves the constraint conflict entirely, no
`rag_documents` change needed.

**User:** asked whether a new discriminator column was needed to tell a
table-descriptor chunk apart from a general-strategy chunk.

**Assistant:** No — `document_chunks.block_type = 'table'` already serves
that purpose.

**User:** "let it be there for now: block_type" — confirmed.

**Implementation:**

- `db/migrations/002_document_tables.sql` — `document_tables(rag_id,
  table_ref, chunk_id, page_number, caption, column_headers jsonb, rows
  jsonb, created_at)`, PK `(rag_id, table_ref)`, FK `(rag_id, chunk_id) ->
  document_chunks`. Applied to `cra_dev`.
- `datamodel.md` updated with the `document_tables` schema and a "two
  chunking strategies, one rag_documents row" section documenting the
  rationale (including the real retrieval-ranking numbers from the dilution
  test).
- `regulation_pipeline/chunking/table_extractor.py` — new module. Walks a
  `DoclingDocument` via `iterate_items()` (verified this API directly rather
  than guessing), and for each `TableItem` builds a `TableDescriptor`
  (context + column headers, not row data) plus the structured `rows`. A
  `to_chunk()` function converts a descriptor into the existing `Chunk`
  dataclass so it can reuse `docling_hybrid_chunker`'s embedding/storage path
  unchanged.
- `pgvector_embedder.py` — added `store_document_tables()` and
  `embed_and_store_tables()` (converts descriptors to chunks, reuses
  `embed_and_store`, then writes `document_tables`).
- 3 new unit tests in `test_table_extractor.py`, 2 new in
  `test_pgvector_embedder.py` (all passing, hermetic — synthetic
  `DoclingDocument`s built directly, no live PDF/DB needed).

**Validation against the real PDF surfaced three distinct real bugs**, found
only by testing against `1_RCNY_103-14.pdf`'s actual page 42-44 tables (a
single logical ~60-row property-type list Docling splits into three
`TableItem`s per page boundary), not by the unit tests:

1. **Continuation table with no header at all** (table `#9`, page 43) — fixed
   by inheriting the previous table's headers when column count matches and
   no section boundary intervened.
2. **Continuation table where Docling flagged the *wrong* row as the header**
   (table `#9`'s actual failure: "Museum"/"0.01181", a real data pair, marked
   `column_header=True`) — required overriding Docling's flag outright, not
   just falling back when headers are empty, plus not silently dropping that
   row from `rows` (it was being skipped as if it were a real header row).
3. **Genuinely different table, same column count, immediately adjacent, own
   real header — but Docling never flagged it** (table `#10`, page 44: the
   real header `"ESPM Property Type" | "2030-2034 Emissions Factor..."` sits
   as an ordinary unflagged first grid row). The fix for (1)/(2) wrongly
   swallowed this into the same continuation logic. Required a third signal:
   check whether a table's own first row looks like a header (non-numeric
   cells) before falling back to inheritance — added `_looks_like_real_header()`
   (a header is a text label, not a bare number) as a plausibility check used
   at two decision points: trusting Docling's flag, and trusting the grid's
   raw first row.

Final `_resolve_table()` tries, in order: Docling's flagged header (if
plausible) → the grid's own first row as an unflagged header (if plausible)
→ inherit from an adjacent same-shaped previous table → no header. Each of
the three bugs got a dedicated regression test mirroring the real failure
before being fixed, not just a passing-case test.

**Final validation, live against `1_RCNY_103-14.pdf`:** all four compliance
periods (2024-29, 2030-34, 2035-39, 2040-49) — 8 tables total across their
page-boundary continuations — now show correct, matching period headers.
Row counts shifted in both directions vs. the buggy version: some tables
gained a row (previously silently dropped as a misdetected header), others
lost one (previously double-counted a real header as data) — both changes
independently confirm correctness, not just different output.

**User:** "can clean the tables and run the entire json" — cleared the old
buggy `document_tables` rows and table-descriptor chunks (`chunk_id >= 39`)
for `rag_id = 6`, kept the 39 general-strategy chunks untouched, reran the
fixed extractor against the full PDF. All 26 tables re-extracted; the 8
property-type tables all correct.

---

## Where this leaves off

- `regulation_pipeline/chunking/table_extractor.py` is real, tested (5 unit
  tests), and validated against live data with three distinct real bugs found
  and fixed through iteration against the actual PDF, not assumed correct
  from unit tests alone.
- `cra_dev`, `rag_id = 6`: 39 general-strategy chunks (0-38, from
  `04-...md`'s work) + 26 table-descriptor chunks (39-64, `block_type =
  'table'`) + 26 `document_tables` rows — all current, all from the fixed
  extractor.
- Retrieval-dilution problem (the reason this strategy exists) is
  empirically fixed for the property-type tables — not re-verified with a
  fresh retrieval-ranking test after this session's rewrite, but the earlier
  version of the fix (before the continuation-header bugs were found) was
  confirmed to rank the target table near the top instead of #11/39.
- Smaller/more esoteric tables (`#0`, `#16`-`#25`: fuel coefficients, TOU/
  campus-system formulas) still have less clean headers (`'Mon*'`, `'='`,
  `'per kBtu)'`) — not addressed, out of scope for this pass, noted but not
  filed as a formal follow-up.
- Still not built: the actual LLM confirm/classify step (retrieval →
  "which table is this" → deterministic extraction into
  `emissions_factors`/etc.) — only the descriptor + storage half exists so
  far, not the retrieval-to-extraction pipeline itself.
- `pipeline_runs`/`pipeline_steps` bookkeeping around a real ingest run is
  still not wired up — `rag_id`/chunk numbering is still managed by hand in
  scratch smoke-test scripts, not a real orchestrator.
