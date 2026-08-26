-- 002_document_tables.sql
-- Structured table payloads produced by the table-extraction chunking
-- strategy. Discovered/pointed to via a compact descriptor row in
-- document_chunks (block_type = 'table'); the descriptor is what gets
-- embedded and searched, this table holds the actual row data.
-- See datamodel.md for the design rationale.

CREATE TABLE document_tables (
    rag_id          INT NOT NULL REFERENCES rag_documents(rag_id),
    table_ref       TEXT NOT NULL,
    chunk_id        INT NOT NULL,
    page_number     INT,
    caption         TEXT,
    column_headers  JSONB,
    rows            JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rag_id, table_ref),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id)
);

CREATE INDEX ON document_tables (rag_id, chunk_id);
