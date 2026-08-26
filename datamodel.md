# Data Model

Status: ingestion/RAG pipeline tables are finalized below. Extraction-output tables
(emissions factors, fuel coefficients, penalty rules, covered-building rules) are
deferred until we design the extraction stage itself.

## pipeline_runs

One row per triggered batch job / file processing run.

| column        | notes                                                              |
|---------------|---------------------------------------------------------------------|
| id            | PK                                                                   |
| status        |                                                                       |
| force_regen   | forces reprocessing even if `document_hash` on `rag_documents` is unchanged |
| batch_job_id  |                                                                       |
| started_at    |                                                                       |
| completed_at  |                                                                       |
| error         |                                                                       |
| created_at    |                                                                       |
| doc_type      | known at trigger time (statute / regulation / ordinance)            |
| rag_id        | FK to `rag_documents.rag_id`, populated once the run produces a document version |

## pipeline_steps

Per-step observability within a `pipeline_run` (e.g. ingest, chunk_embed, extract, persist).

| column        | notes                          |
|---------------|---------------------------------|
| id            | PK                              |
| run_id        | FK to `pipeline_runs.id`        |
| step_name     |                                  |
| status        |                                  |
| attempt       | retry count                     |
| started_at    |                                  |
| completed_at  |                                  |
| duration_ms   |                                  |
| error         |                                  |
| meta          | step-specific detail            |
| created_at    |                                  |

## rag_documents

One row per ingested/embedded version of a source document. `document_key` is the
stable logical identity across versions; `version_id` + `active_flag` let a document
be re-ingested (e.g. after a regulatory amendment, or an `embed_model` change)
without losing history.

| column        | notes                                     |
|---------------|--------------------------------------------|
| rag_id        | PK                                          |
| document_key  | stable logical identity (no separate `documents` master table — this is the sole document reference) |
| document_hash | used for change detection / skip logic     |
| run_id        |                                              |
| chunk_count   |                                              |
| embed_model   |                                              |
| created_at    |                                              |
| version_id    |                                              |
| active_flag   | marks the current version used for retrieval |

## document_chunks

RAG index entries produced by Docling parsing + `HybridChunker`.

| column        | notes                                                          |
|---------------|-------------------------------------------------------------------|
| rag_id        | FK to `rag_documents.rag_id`                                       |
| chunk_id      | PK together with `rag_id`: `(rag_id, chunk_id)`                    |
| document_key  |                                                                     |
| page_number   |                                                                     |
| block_type    | Docling's raw layout classification (paragraph, table, heading, list-item, etc.) |
| section       |                                                                     |
| section_path  |                                                                     |
| raw_text      |                                                                     |
| full_text     |                                                                     |
| chunk_meta    |                                                                     |
| created_at    |                                                                     |

## chunk_embeddings

Vector embeddings per chunk, split out from `document_chunks` so a chunk can be
re-embedded under a different model without duplicating text.

| column      | notes                                                       |
|-------------|---------------------------------------------------------------|
| rag_id      | FK, together with `chunk_id`, to `document_chunks(rag_id, chunk_id)` |
| chunk_id    |                                                                 |
| embedding   |                                                                 |
| model_name  |                                                                 |
| created_at  |                                                                 |

## document_tables

Structured table payloads. Populated by the table-extraction chunking
strategy, discovered/pointed to via a compact descriptor row in
`document_chunks` (`block_type = 'table'`) — the descriptor is what gets
embedded and searched; this table holds the actual row data, read
deterministically (no LLM numeric transcription) once a table is identified
as relevant.

| column         | notes                                                              |
|----------------|----------------------------------------------------------------------|
| rag_id         | FK to `rag_documents.rag_id`                                          |
| table_ref      | Docling `self_ref` for the table, e.g. `"#/tables/8"` — unique within a `rag_id` |
| chunk_id       | FK, together with `rag_id`, to `document_chunks(rag_id, chunk_id)`: the descriptor chunk that points here |
| page_number    |                                                                        |
| caption        |                                                                        |
| column_headers | jsonb array of strings                                                |
| rows           | jsonb array of objects, keyed by column header — not raw/flattened text, so downstream extraction can read it directly |
| created_at     |                                                                        |

PK: `(rag_id, table_ref)`.

## Two chunking strategies, one rag_documents row

Both strategies run against the same ingested document version — one
`rag_documents` row per document, not one per strategy. No new column needed
to tell their output apart; `document_chunks.block_type` already
discriminates (`'table'` for descriptor rows, everything else from the
general pass).

- **General** — today's `docling_hybrid_chunker.py` / `HybridChunker`.
  Prose + tables flattened together into `document_chunks`. Good enough for
  open-ended Q&A (a chat-style use case) where surgical numeric precision
  isn't required.
- **Table-extraction** — walks the document, and for each `TableItem` builds
  a small descriptor chunk (heading path + intro sentence + column headers,
  *not* the row data) into `document_chunks`, plus the full structured
  content into `document_tables`. Purpose-built for the
  emissions-factors/coefficients extraction pipeline: retrieval finds the
  descriptor (sharp embedding, since it's short and single-topic), an LLM
  confirms which table, then extraction reads `document_tables.rows`
  directly — no LLM transcription of the actual numbers.

Why not just one strategy: tested retrieval against the real stored
`1_RCNY_103-14.pdf` chunks (`rag_id = 6`, produced by the general strategy)
and found the chunk containing three of the four target emissions-factor
tables ranked #11 of 39 by cosine similarity against a query for exactly that
content — behind unrelated penalty text and narrative preamble. The chunk is
20,009 characters (tables + surrounding prose merged under one section
header), and its embedding is a blurry average of everything in it. Small,
single-topic descriptor chunks fix this because they don't dilute.

## Deferred: extraction output tables

Tables for `emissions_factors`, `fuel_coefficients`, `penalty_rules`,
`covered_building_rules` — to be designed when we build the extraction stage.
`jurisdiction` will live on these tables as an **extracted field** (not on
`rag_documents`/`document_chunks`), since jurisdiction is inferred from document
content by the extraction model rather than assumed from file naming or folder
structure. Each row is expected to ground back to a `(rag_id, chunk_id)`.

## Standing design decisions

- Vector store: pgvector inside the same local Postgres instance (not a separate vector DB)
- Embedding model: `nomic-embed-text-v1`, loaded in-process via `sentence-transformers` per embedding run (not served from Ollama)
- PDF parsing/chunking: Docling (provenance-aware, table-structure-preserving); two chunking strategies — see above
- Jurisdictions in scope: NYC + Boston, built generically — no per-city schema
- Extraction LLM: Claude via the Anthropic API
