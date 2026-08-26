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

## Deferred: extraction output tables

Tables for `emissions_factors`, `fuel_coefficients`, `penalty_rules`,
`covered_building_rules` — to be designed when we build the extraction stage.
`jurisdiction` will live on these tables as an **extracted field** (not on
`rag_documents`/`document_chunks`), since jurisdiction is inferred from document
content by the extraction model rather than assumed from file naming or folder
structure. Each row is expected to ground back to a `(rag_id, chunk_id)`.

## Standing design decisions

- Vector store: pgvector inside the same local Postgres instance (not a separate vector DB)
- Embedding model: `nomic-embed-text-v1` via local Ollama
- PDF parsing/chunking: Docling (provenance-aware, table-structure-preserving, `HybridChunker`)
- Jurisdictions in scope: NYC + Boston, built generically — no per-city schema
- Extraction LLM: Claude via the Anthropic API
