-- 001_init.sql
-- Ingestion / RAG pipeline schema for cra_dev.
-- See datamodel.md at repo root for the design rationale.

CREATE EXTENSION IF NOT EXISTS vector;

-- pipeline_runs and rag_documents reference each other (a run produces a
-- document version; a document version records which run produced it), so
-- pipeline_runs.rag_id's FK is added after rag_documents exists, below.
CREATE TABLE pipeline_runs (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status        TEXT NOT NULL,
    force_regen   BOOLEAN NOT NULL DEFAULT false,
    batch_job_id  TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    doc_type      TEXT,
    rag_id        INT
);

CREATE TABLE pipeline_steps (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id        INT NOT NULL REFERENCES pipeline_runs(id),
    step_name     TEXT NOT NULL,
    status        TEXT NOT NULL,
    attempt       INT NOT NULL DEFAULT 1,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    duration_ms   INT,
    error         TEXT,
    meta          JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ON pipeline_steps (run_id);

CREATE TABLE rag_documents (
    rag_id         INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_key   TEXT NOT NULL,
    document_hash  TEXT NOT NULL,
    run_id         INT REFERENCES pipeline_runs(id),
    chunk_count    INT,
    embed_model    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    version_id     INT NOT NULL,
    active_flag    BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX ON rag_documents (document_key);

-- Only one active version per document_key at a time.
CREATE UNIQUE INDEX rag_documents_one_active_per_key
    ON rag_documents (document_key)
    WHERE active_flag;

ALTER TABLE pipeline_runs
    ADD CONSTRAINT pipeline_runs_rag_id_fkey
    FOREIGN KEY (rag_id) REFERENCES rag_documents(rag_id);

CREATE TABLE document_chunks (
    rag_id        INT NOT NULL REFERENCES rag_documents(rag_id),
    chunk_id      INT NOT NULL,
    document_key  TEXT NOT NULL,
    page_number   INT,
    block_type    TEXT,
    section       TEXT,
    section_path  TEXT,
    raw_text      TEXT,
    full_text     TEXT,
    chunk_meta    JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rag_id, chunk_id)
);

CREATE INDEX ON document_chunks (document_key);

-- nomic-embed-text-v1 produces 768-dim embeddings.
CREATE TABLE chunk_embeddings (
    rag_id      INT NOT NULL,
    chunk_id    INT NOT NULL,
    embedding   VECTOR(768) NOT NULL,
    model_name  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rag_id, chunk_id, model_name),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id)
);

-- No vector similarity index (ivfflat/hnsw) yet: those are tuned against real
-- data volume/distribution, which we don't have until chunks are loaded.
