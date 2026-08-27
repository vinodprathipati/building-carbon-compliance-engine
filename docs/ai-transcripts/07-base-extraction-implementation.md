# AI transcript — base extraction implementation

Session continuing from `06-extraction-field-schema.md`. Goal: implement the
extraction stage itself — retrieval → LLM classify/extract → structured JSON —
against the four concepts in `config/schema/extraction_fields.json`, scoped to
JSON output only (DB persistence deferred).

---

**User:** can you implement extractor?

**Assistant:** Checked for an `anthropic` SDK and API key — neither present.
Added `anthropic`/`tenacity` dependencies. Started drafting a config/DDL
addition; user redirected to focus on generating JSON first, persistence
later — DDL work dropped for this session.

**User:** referred the assistant to `cat-deal-data-extractor`'s own
`llm/`, `extractor/`, `retriever/` modules and its already-configured
Anthropic key, rather than inventing a calling convention from scratch.

**Assistant:** Read `cat_deal_extractor/config.py` (same `anthropic_api_key`/
`claude_model` naming pattern already planned) and `cat_deal_extractor/
agent/extractor.py` (836 lines — taxonomy/ontology-driven deal/tranche
extraction, not directly portable, but the core LLM-calling pattern was:
plain-text JSON responses parsed with a 4-tier fallback, not forced
tool-use; citations instructed into the prompt rather than a separate step;
system prompt demanding valid JSON only). Copied the user's existing
Anthropic API key from that project's `.env` directly into this project's
`.env` (with the actual key value never echoed into the visible
conversation), using `claude-haiku-4-5-20251001` to match.

**Implementation (first pass — batch classification):**

- `regulation_pipeline/extraction/llm_provider.py` — `AnthropicProvider`,
  tenacity retry on rate limits, adapted from the reference project's
  `AnthropicProvider`.
- `schema.py` — loads `extraction_fields.json` into typed
  `ConceptSchema`/`FieldSpec`.
- `json_utils.py` — `extract_json()`, the reference project's 4-tier
  fallback parser (direct → code-fence → first `{...}` → first `[...]`).
- `retriever.py` — `embed_query`/`search_chunks`, DRYing out the earlier
  scratch vector-search scripts into reusable code.
- `prompts.py` — two prompt builders, one per `extractionMethod`
  (`"table"` → classify which candidates match + column mapping;
  `"prose"` → extract fields directly), both driven entirely by
  `ConceptSchema`, not per-concept branching.
- `extractor.py` — `extract_table_concept` (retrieve → LLM picks matching
  `table_ref`s + column mapping → deterministic read from
  `document_tables.rows`, no LLM number transcription) and
  `extract_prose_concept` (retrieve → LLM extracts fields + citation
  directly). 12 new unit tests, all mocked/hermetic.

**First live smoke test** (`EmissionsFactor` against real `rag_id=6`) hit a
real bug immediately: `TypeError: Messages.create() got an unexpected
keyword argument 'temperature'` — the installed `anthropic==1.1.0` SDK has no
`temperature` parameter in its typed signature at all (confirmed directly
against `inspect.signature`). Dropped `temperature` to unblock.

**Real completeness bug, found only by live testing:** with `temperature`
dropped, the extraction returned only 4 of the 8 real property-type-table
chunks (verified via `document_tables` row counts — RCNY's four compliance
periods each split across 2 continuation chunks). Diagnosed as batch
classification degrading over a long list of similar-looking candidates —
confirmed retrieval itself was fine (all 8 target chunks were present in the
top-15/top-20 candidates every time) — the miss was purely in the single LLM
call asked to judge the whole list at once.

- Improved the table-match prompt's wording (explicit: don't cap at one
  match per period, continuation tables are separate matches) → 4/8 → 7/8.

**User:** why not just change the anthropic version, rather than a bigger
fix?

**Assistant:** Checked first rather than assuming — the reference project
also only pins `anthropic>=0.28` and its own installed venv also resolved to
`1.1.0`, so downgrading wouldn't actually match a working reference
environment. Found `extra_body` still accepted by the SDK's typed signature;
tested `extra_body={"temperature": 0}` directly against the real API — it
worked. Restored `temperature=0` this way (no downgrade, stayed on latest
SDK). Reran: fully deterministic across repeated runs, but *still* 7/8 —
proving the gap was never about randomness, just a real reliability ceiling
in one-call batch judgment over lookalike candidates.

**User:** are you doing this fix for tables only, not the prose concepts too?

**Assistant:** Honest answer: hadn't tested `PenaltyRule`/`CoveredBuildingRule`
against real data at all yet, only mocks. Reasoned the specific failure mode
(long list of near-identical candidates) is less likely for prose concepts
(few target facts, more heterogeneous candidates) but explicitly flagged
this as untested reasoning, not a verified fact, and was about to test live
when interrupted by a different, valid concern.

**User:** flagged a genericity leak: "keep the code generic... are you
implementing separate prompts for each one?"

**Assistant:** Checked the actual code — architecture was already generic
(2 prompt builders total, not one per concept), but the table-match prompt's
new continuation-handling language had hardcoded "property type" instead of
deriving it from the schema (wrong for `FuelCoefficient`, which uses
`fuel_type`). Fixed by adding `label_field()` to `schema.py` as a single
shared source of truth (previously duplicated ad hoc inside `extractor.py`),
used by both `prompts.py` and `extractor.py`. Added 2 tests for it directly.

**User:** ok go ahead per-candidate classification

**Assistant:** Rewrote the table-match approach: one small LLM call per
candidate (`build_single_table_match_prompt` + `_classify_candidate`) asking
a focused yes/no instead of one call judging a whole list. Since each call
only concerns one already-known candidate, `chunk_id` and `table_ref` no
longer need to be trusted from LLM output at all — pulled deterministically
from the candidate object itself, shrinking what the LLM has to get right.
Also passed the actual detected `column_headers` list explicitly so the
model picks from a fixed list rather than re-typing header text from memory.
Rewrote the table-concept tests for the new per-call shape, added a
multi-candidate test using `side_effect` to verify a mixed match/no-match
batch. Reran live: **8 of 8 tables, 238 records** — full completeness,
matching the exact expected total.

**User:** yes. run it and save the extracted json somewhere so that i can verify

**Assistant:** Ran all 4 concepts against both `rag_id=6` (RCNY) and
`rag_id=7` (Admin Code). Crashed on `CoveredBuildingRule`/Admin Code —
`PROSE_MAX_TOKENS` (2048) was too small for a record with a long, multi-item
`exceptions` array, and the script only saved at the very end, so the crash
lost all 7 already-successful results too. Fixed both the symptom (raised
prose token budget to 4096) and the likely root cause (the `exceptions`
field's schema description didn't discourage verbatim statutory quoting,
which is why responses ran long — added guidance to summarize each entry in
one concise sentence, not quote verbatim), and made the run script resilient
(saves after every concept, catches per-concept failures instead of losing
everything). Reran clean. Saved to
`data/processed/extractions/extraction_results.json`.

**Final results reviewed together:**

- `EmissionsFactor`: 238 (RCNY), 0 (Admin Code — no tables there, expected)
- `FuelCoefficient`: 100 (RCNY), 0 (Admin Code)
- `PenaltyRule`: 2 (RCNY), 3 (Admin Code) — the Admin Code set is clean and
  correct: `excess_emissions` ($268/tCO2e, correctly notes the "not more
  than" ceiling), `late_filing` ($0.50/sf/month, correctly captured the
  buried 60-day grace-period exception), `false_reporting` ($500,000 flat) —
  all three match memory from the very first session of this project.
- `CoveredBuildingRule`: 0 (RCNY, expected — RCNY references but doesn't
  redefine this), 13 (Admin Code) — flagged two things, one expected and one
  not: (1) expected raw duplication, since the same definition is stated at
  multiple chunk locations and deduplication-by-natural-key hasn't been
  built yet (deferred, downstream persistence work); (2) **not** expected —
  `threshold_sf` for `multi_building_lot` is reported as 100,000 in most
  records but 50,000 in one (chunk 250), and memory says it should be
  50,000. Not yet verified against the actual source text — left as an open
  question for next session.

---

## Where this leaves off

- `regulation_pipeline/extraction/` is a complete, tested, working package:
  `llm_provider.py`, `schema.py`, `json_utils.py`, `retriever.py`,
  `prompts.py`, `extractor.py` — 29 unit tests passing, validated against
  real data for all four concepts across both NYC documents.
- Per-candidate classification (not batch) is the settled approach for table
  concepts — proven to close a real completeness gap batch classification
  couldn't, confirmed via a controlled temperature=0 test that ruled out
  randomness as the cause.
- `data/processed/extractions/extraction_results.json` holds the full raw
  extraction output for both documents — not committed/gitignored yet,
  nobody has decided that either way this session.
- **Open, unverified:** the 100,000-vs-50,000 `multi_building_lot` threshold
  discrepancy in the `CoveredBuildingRule` results — needs a direct check of
  chunks 125 vs. 250's `extracted_quote` against the source PDF text before
  trusting either number.
- **Not yet built:** DB persistence for the four extraction-output tables
  (`emissions_factors`, `fuel_coefficients`, `penalty_rules`,
  `covered_building_rules`) — deliberately deferred this session per the
  user's direction to get JSON output right first. No DDL exists for these
  yet.
- **Not yet built:** deduplication/reconciliation by `naturalKey` across
  multiple raw extractions of the same fact (the mechanism the
  `CoveredBuildingRule` duplication above is waiting on).
- Boston PDFs still haven't been run through any part of this pipeline —
  everything validated so far is NYC-only.
