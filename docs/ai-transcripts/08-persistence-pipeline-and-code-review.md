# AI transcript — persistence, pipeline orchestration, and code review

Session continuing from `07-base-extraction-implementation.md`. Goal: persist
extraction output to Postgres and wire chunking → embedding → extraction into
one orchestrated pipeline, then address code-review observations from the
user's own read-through of the result.

---

## Part 1 — Persistence + orchestration

**User:** "Let's work on two things: Persisting data to Postgres tables and
plumbing all together chunking, embedding and extraction."

**Assistant:** Built both.

- `db/migrations/003_extraction_tables.sql` — four extraction-output tables.
  Deliberately different uniqueness strategy per table: `emissions_factors`/
  `fuel_coefficients` get a tight natural-key constraint (each fact lives in
  exactly one place in a source table); `penalty_rules`/`covered_building_rules`
  get a looser `(rag_id, chunk_id, ...)` constraint instead — prose facts are
  legitimately restated at multiple chunk locations in the same document
  (confirmed earlier: the Admin Code's covered-building definition appears 5
  times, with one location disagreeing on the actual number), so a natural-key
  constraint would silently pick an arbitrary winner among conflicting
  extractions with no visibility that a conflict happened.
- `regulation_pipeline/extraction/persist.py` — one store function per
  concept, `ON CONFLICT DO NOTHING`.
- `regulation_pipeline/pipeline.py` — `run_pipeline()`, finally putting
  `pipeline_runs`/`pipeline_steps` (designed weeks earlier, never used) to
  real use. Hash-based skip logic: an unchanged PDF re-run reuses the
  existing `rag_id` and skips re-parsing/re-embedding entirely.

**Live validation surfaced three real, distinct bugs** (unit tests, being
mocked, caught none of them):

1. **Cascading error-handling failure.** A DB error mid-step left Postgres in
   an aborted-transaction state; the code's own failure-recording update then
   failed too (`InFailedSqlTransaction`), so a crash produced no clean
   `pipeline_steps`/`pipeline_runs` failure record — just a raw traceback.
   Fixed by adding `conn.rollback()` before any failure-path write, both in
   `_run_step` and defensively in `run_pipeline`'s top-level handler.
2. **Malformed multi-value cell.** One real `EmissionsFactor` value came back
   as `"0.004329281 0.003459842"` — two numbers concatenated, traced to a
   genuine PDF table-structure quirk (two source rows on page 46 that Docling
   merged into one during table detection; not confidently un-mergeable
   without deeper geometry inspection). Rather than crash the whole batch,
   `persist.py` now validates every numeric field via `Decimal()` parsing
   before insert and skips (with a logged reason) any record that fails —
   238 of 239 records for that table still land correctly.
3. **Missing required fields the LLM was being honest about.** Two related
   findings: (a) a general combustion-fuel table (not period-scoped, unlike
   the property-type tables) correctly returned `period_start`/`period_end`
   as null, which then violated the original `NOT NULL` constraint — fixed by
   making those columns nullable on `fuel_coefficients` specifically (schema
   was wrong to assume every fuel table is period-scoped) — migration
   `004_fuel_coefficients_nullable_period.sql`; (b) the same table candidate
   also returned `jurisdiction: null` (couldn't confidently infer it from its
   own narrow context) — generalized `persist.py`'s validation to check
   *every* required field per table, not just numeric ones, after hitting a
   second distinct `NOT NULL` violation in a row rather than continuing to
   patch one column at a time.

**A fourth, more serious issue found by inspection, not a crash:** reviewing
stored data after a clean run showed most `jurisdiction` values were a
placeholder string — `"Not specified in provided text"` (73% of
`emissions_factors`, 100% of `fuel_coefficients`) — not `null` (which
validation would have caught) and not `"New York City"`. Root cause:
jurisdiction was being re-derived independently on every single per-candidate
LLM call from only that candidate's narrow, isolated text — and most
candidates deep in a technical rule don't repeat the city name the way the
document's title does. Diagnosed as an architecture problem, not a prompt
tweak: jurisdiction is a per-*document* constant, not a per-fact property, and
should be resolved once and reused (matching the `cat-deal-data-extractor`
reference project's `_extract_identity_fields()` pattern) rather than
re-guessed on every call. **Not yet fixed** — flagged and deferred.

## Part 2 — Code review

**User (three observations from reading the code):**

1. "I want to include three major steps [in pipeline_steps]. 1) parsing
   2) Embedding 3) extraction."

   `_ingest_general`/`_ingest_tables` each bundled Docling parsing and
   embedding into one opaque tracked step. Split into `_parse_document`
   (Docling only, no DB writes, returns chunks/descriptors + a small meta
   dict) and `_embed_document` (embedding + pgvector storage only), wired via
   a local dict closure so `_run_step`'s tracked `fn()` can still return just
   the JSON-serializable meta while the actual chunk objects pass between
   steps without going through that channel. Live-validated with a
   force-regen run: `parsing` (16.4s), `embedding` (16.0s), `extraction`
   (21.1s) now show up as three separate `pipeline_steps` rows with
   independent timing.

2. "I see you are using Inline SQLs, Can you please avoid this... What is the
   correct way? skills.md or claude.md?"

   Answered directly: CLAUDE.md, not a skill — skills are for invokable
   multi-step procedures, CLAUDE.md is for standing conventions that should
   be ambient context every call. Proposed per-query `.sql` files initially;
   user redirected to one consolidated file for easy scanning. Built
   `regulation_pipeline/db/queries.sql` (18 named queries, `-- name: x`
   markers) + `regulation_pipeline/db/queries.py` (`sql(name)` lookup,
   cached), and moved every inline `cur.execute("...")` across `pipeline.py`,
   `persist.py`, `pgvector_embedder.py`, `extractor.py`, and `retriever.py`
   (found this last one by a full-codebase grep sweep, not initially in
   scope) to use it. Documented as a CLAUDE.md convention.

3. "Prompts are part of the code. Can we separate prompts for Maintainability
   and Clean Code."

   Same pattern, same reasoning — generalized the SQL loader into
   `regulation_pipeline/text_blocks.py` (shared by both `queries.sql` and the
   new `extraction/prompt_templates.txt`) rather than duplicating the parsing
   logic. Prompts use `str.format()` placeholders; literal braces in a
   template (JSON examples) escape as `{{`/`}}`. Verified the rendered output
   is byte-for-byte identical to the pre-refactor f-strings by diffing both
   directly — a pure relocation, not a behavior change, so no live LLM
   re-validation was needed.

All 47 tests pass throughout every step of both parts.

---

## Where this leaves off

- `regulation_pipeline/pipeline.py` is the real orchestration entrypoint:
  parsing → embedding → extraction, each independently tracked in
  `pipeline_steps`, with hash-based skip logic and clean failure recording.
- Persistence is real — `emissions_factors`, `fuel_coefficients`,
  `penalty_rules`, `covered_building_rules` all have live data from actual
  pipeline runs, not just JSON exports.
- **Not fixed, real and known:** jurisdiction is still re-derived per-call
  rather than resolved once per document. Current data is usable for the
  property-type/fuel tables that *did* get "New York City" right, but a
  majority of rows carry placeholder text instead. Proposed fix (extract
  once up front, stamp onto every record) is agreed in principle, not
  implemented.
- Two new standing conventions in `CLAUDE.md`: no inline SQL
  (`db/queries.sql`), no inline prompts (`extraction/prompt_templates.txt`) —
  both loaded via the shared `text_blocks.py`.
- Nothing from this session is committed to git yet.
- `rag_id`s have accumulated some debugging-run cruft (e.g. `rag_id=9` from a
  force-regen validation run) — not cleaned up, not urgent.
