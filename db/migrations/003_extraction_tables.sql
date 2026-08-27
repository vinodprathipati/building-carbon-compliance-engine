-- 003_extraction_tables.sql
-- Extraction-output tables: the structured facts pulled out of regulation
-- documents, grounded back to the chunk they came from. Field shapes match
-- config/schema/extraction_fields.json. See datamodel.md.
--
-- emissions_factors / fuel_coefficients: each fact genuinely lives in one
-- place in the source table, so a natural-key uniqueness constraint is safe
-- and catches real bugs (accidental double-insert of the same fact).
--
-- penalty_rules / covered_building_rules: prose-sourced facts can be
-- legitimately restated at multiple chunk locations in the same document
-- (confirmed on covered_building_rules — the same threshold definition
-- appears 5 times in NYC_AdminCode_Chapter3.pdf, with one location
-- disagreeing on the actual number). A natural-key constraint here would
-- silently pick an arbitrary winner among conflicting extractions with no
-- visibility that a conflict happened. So uniqueness is scoped to
-- (rag_id, chunk_id, ...) instead — idempotent re-extraction of the same
-- chunk, not cross-chunk deduplication. Reconciling multiple chunks' facts
-- into one canonical row is a deliberate, separate, visible step.

CREATE TABLE emissions_factors (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rag_id            INT NOT NULL REFERENCES rag_documents(rag_id),
    chunk_id          INT NOT NULL,
    jurisdiction      TEXT NOT NULL,
    property_type     TEXT NOT NULL,
    period_start      INT NOT NULL,
    period_end        INT NOT NULL,
    value             NUMERIC NOT NULL,
    unit              TEXT NOT NULL,
    extracted_quote   TEXT,
    extraction_model  TEXT,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id),
    UNIQUE (rag_id, jurisdiction, property_type, period_start, period_end)
);

CREATE TABLE fuel_coefficients (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rag_id            INT NOT NULL REFERENCES rag_documents(rag_id),
    chunk_id          INT NOT NULL,
    jurisdiction      TEXT NOT NULL,
    fuel_type         TEXT NOT NULL,
    period_start      INT NOT NULL,
    period_end        INT NOT NULL,
    value             NUMERIC NOT NULL,
    unit              TEXT NOT NULL,
    extracted_quote   TEXT,
    extraction_model  TEXT,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id),
    UNIQUE (rag_id, jurisdiction, fuel_type, period_start, period_end)
);

CREATE TABLE penalty_rules (
    id                   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rag_id               INT NOT NULL REFERENCES rag_documents(rag_id),
    chunk_id             INT NOT NULL,
    jurisdiction         TEXT NOT NULL,
    rule_type            TEXT NOT NULL,
    period_start         INT,
    period_end           INT,
    rate                 NUMERIC NOT NULL,
    rate_unit            TEXT NOT NULL,
    formula_description  TEXT,
    extracted_quote      TEXT,
    extraction_model     TEXT,
    extracted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id),
    UNIQUE (rag_id, chunk_id, jurisdiction, rule_type)
);

CREATE TABLE covered_building_rules (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rag_id            INT NOT NULL REFERENCES rag_documents(rag_id),
    chunk_id          INT NOT NULL,
    jurisdiction      TEXT NOT NULL,
    threshold_type    TEXT NOT NULL,
    threshold_sf      NUMERIC NOT NULL,
    aggregation_rule  TEXT,
    exceptions        JSONB,
    extracted_quote   TEXT,
    extraction_model  TEXT,
    extracted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (rag_id, chunk_id) REFERENCES document_chunks(rag_id, chunk_id),
    UNIQUE (rag_id, chunk_id, jurisdiction, threshold_type)
);
