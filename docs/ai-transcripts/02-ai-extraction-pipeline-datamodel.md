# AI transcript — two-pipeline architecture + RAG ingestion data model

Session continuing from `01-scaffold.md`. Goal: design a two-pipeline architecture
(AI extraction from regulation PDFs, and a disclosure data pipeline feeding a
Streamlit UI), then work out the concrete data model for the AI extraction
pipeline's ingestion/RAG layer.

---

**User:** now, if you understand, I want to build two separate pipelines. One of
them is AI pipeline to extract factors and penaltities information from raw pdfs
by parsing the PDFs. The other one is data pipeline to load disclosures. During
the disclosure load, we calculate the projections. These projections can be
integrated with a simple streamlit UI. This is high level approach.

**Assistant:** Proposed a two-pipeline split:

- **Pipeline 1 — AI extraction (PDFs → structured factors):** turn the RCNY/Admin
  Code/BERDO PDFs into a structured, versioned artifact instead of hardcoded
  numbers in scripts — `{jurisdiction, source_doc, page, effective_period,
  property_type|fuel_type, value, unit}`. Flagged that extraction accuracy needs a
  validation step (a golden set), since a wrong coefficient cascades into wrong
  penalties across thousands of buildings.
- **Pipeline 2 — Data pipeline (disclosures → projections):** load disclosure
  CSV/XLSX + covered-buildings list, clean (BBL normalization, dedupe, "Not
  Available" handling), join to the compliance universe, run the two-step calc
  (fuel × coefficient → actual; GFA × cap factor → allowed) using Pipeline 1's
  output as the rules source, then extend across future compliance periods.
- **Streamlit UI** reads Pipeline 2's output.

Asked two clarifying questions: how "projections" should be computed for future
compliance periods, and which jurisdiction(s) to target first.

**User (answers):** On projections — redirected into a much more detailed AI
extraction design instead: parse the PDF, build RAG, store embeddings in a vector
DB, use the local Postgres instance, make extraction generic across any
municipality, extract grounding information for data lineage, store extracted
info in a relational table. On jurisdiction scope: NYC + Boston together.

**Assistant:** Laid out a 4-stage AI extraction architecture:

1. **Ingest & parse** — extract text per page into `documents`/`document_pages`.
2. **Chunk & embed (RAG index)** — page-anchored chunking, embeddings stored
   alongside chunk text.
3. **Retrieve & extract (grounded)** — per extraction target (emissions-cap
   table, fuel coefficients, penalty formula, covered-building thresholds),
   retrieve top-k chunks, have the LLM return a citation (chunk + quote) per
   extracted value.
4. **Persist with lineage** — structured facts land in relational tables, each
   row FK'd to its source chunk, so any number traces back to the exact PDF page
   and quoted text that produced it. `jurisdiction` as a column (not a
   per-city schema) is what makes this generic across municipalities.

Asked where embeddings should live (pgvector vs. a separate vector DB) and what
should generate them (Anthropic has no embeddings API).

**User (answers):** pgvector in the same Postgres. Embedding model:
`nomic-embed-text-v1`.

**Assistant:** Confirmed nomic-embed-text-v1 (768-dim, needs `trust_remote_code`
via sentence-transformers or can be pulled through Ollama, uses
`search_document:`/`search_query:` prefixes). Summarized the settled extraction
architecture and proposed scaffolding (DDL + directory layout), asking whether to
proceed or keep discussing design (amendments/versioning, extraction prompt
schema).

**User:** i have ollama running in my local. I remember, I pulled the nomic, give
me command to start ollama

**Assistant:** Ran `ollama list` — server wasn't running. Attempted to start it
in the background; user interrupted ("I want to start on my own"), so gave the
manual command (`ollama serve`) instead and stopped there.

**User:** it is running. I have docling in my mind to parse the pdf and to
create the chunks. Any other recommendations?

**Assistant:** Recommended sticking with Docling — its per-element provenance
(page number + bounding box) maps directly onto the grounding/lineage
requirement, its table extraction preserves structure instead of flattening
(important given how much accuracy depends on the coefficient/cap tables), and
its `HybridChunker` is structure-aware so it won't split mid-table-row. Mentioned
`unstructured.io` as the main alternative but not meaningfully better here.
Flagged Docling's dependency footprint (torch, layout models, first-run model
download) as a tradeoff worth knowing about.

**User:** let's go with docling.

**Assistant:** Proposed a directory scaffold (`pipelines/extraction/`, `db/`) and
a first-draft Postgres DDL (`documents`, `document_pages`, `document_chunks`,
`emissions_factors`, `fuel_coefficients`, `penalty_rules`,
`covered_building_rules`), and asked to proceed with creating files and running
the migration.

**User:** provided their own data model instead —

```
rag_documents
  rag_id, document_key, document_hash, run_id, chunk_count,
  embed_model, created_at, version_id, active_flag

document_chunks
  rag_id, chunk_id, document_key, page_number, block_type, section,
  section_path, raw_text, full_text, chunk_meta, created_at, chunk_type
```

**Assistant:** Noted `version_id`/`active_flag`/`embed_model` on `rag_documents`
solves document-amendment/re-embedding versioning cleanly. Asked for
clarification on three points (embedding column location, `chunk_type` vs.
`block_type`, chunk-key uniqueness) — first attempted via AskUserQuestion, which
the user rejected in favor of answering directly.

**User:** Here is the data model for chunk_embeddings —

```
chunk_embeddings
  rag_id, chunk_id, embedding, model_name, created_at
```

*(Noted for future sessions: this user prefers to state schema/design answers
directly rather than pick from AskUserQuestion multiple-choice options during
iterative design work — saved as a feedback memory.)*

**Assistant:** Confirmed this settles the chunk-key pattern as composite
`(rag_id, chunk_id)`. Re-asked the remaining two questions in plain text instead.

**User:** May be chunk_type is not necessary. block_type is docling's raw layout
type.

**Assistant:** Dropped `chunk_type`. Re-asked where jurisdiction/doc-level
metadata should live.

**User:** juridiction is retrieved as a extracted field

**Assistant:** Confirmed `jurisdiction` lives on the extraction-output tables
(populated by the extraction model reading the document), not on
`rag_documents`/`document_chunks` — consistent with the "generic across any
municipality" goal, since the pipeline doesn't need to be told upfront which
city a PDF belongs to. Asked whether a separate `documents` master table is
still needed for source file / doc type / title.

**User:** document_key on rag_documents is sufficient on its own.

**Assistant:** Confirmed — no separate documents master table. Offered to draft
the extraction-output tables next, or have the user dictate those too.

**User:** before this i want to tables for pipeline_runs and pipeline_steps.
pipeline_runs table to maintain the record when each time a batch job is
triggered and a file is processed.

```
pipeline_runs
  id, status, force_regen, batch_job_id, started_at, completed_at,
  error, created_at, doc_type, rag_id
```

**Assistant:** Noted `force_regen` likely drives skip logic against
`document_hash`, and `rag_id` gives a bidirectional trace between a run and the
document version it produced. Asked for the `pipeline_steps` model.

**User:** yes *(confirming the above, not yet giving pipeline_steps)*

**Assistant:** Re-asked specifically for the `pipeline_steps` model.

**User:**

```
pipeline_steps
  id, run_id, step_name, status, attempt, started_at, completed_at,
  duration_ms, error, meta, created_at
```

**Assistant:** Confirmed this gives per-step observability within a run
(ingest → chunk/embed → retrieve/extract → persist), with `attempt` for retries.
Summarized the full settled schema (`pipeline_runs`, `pipeline_steps`,
`rag_documents`, `document_chunks`, `chunk_embeddings`) and asked about the
extraction-output tables (deferred to next session).

**User:** Can you create a datamodel.md file with this info. We will work on
extraction models later in the process. I want to export this AI transcripts and
close the session and come back

**Assistant:** Wrote `datamodel.md` (repo root) with the finalized schema and
standing design decisions, and this transcript.

---

## Where this leaves off

- Ingestion/RAG schema is finalized: `pipeline_runs`, `pipeline_steps`,
  `rag_documents`, `document_chunks`, `chunk_embeddings`. See `datamodel.md`.
- **Next session:** design the extraction-output tables (`emissions_factors`,
  `fuel_coefficients`, `penalty_rules`, `covered_building_rules`) — jurisdiction
  lives there as an extracted field, each row grounds back to `(rag_id,
  chunk_id)`.
- **Still open, not yet revisited:** how "projections" across future compliance
  periods should be computed (flat carry-forward vs. trend-based vs.
  user-adjustable in the Streamlit UI) — this question was asked early on and
  got redirected into the AI-extraction design instead of answered.
- No code or migrations have been written yet — this session was schema design
  only.
