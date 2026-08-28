-- 006_covered_buildings.sql
-- NYC DOF's own official LL97 Covered Buildings List — one row per BBL DOF
-- has determined must comply, independent of (and a check against) the
-- >25,000 sf rule computed from disclosure_pipeline Silver data.
--
-- Loaded once via scripts/load_covered_buildings_list.py, not a pipeline —
-- no rag_documents/chunking/embedding, just a direct PDF-table parse. This
-- table records the schema that script writes to; re-run the script to
-- refresh if DOF publishes an updated list (it truncates and reloads).

CREATE TABLE covered_buildings (
    bbl                       TEXT PRIMARY KEY,
    borough                   TEXT,
    block                     TEXT,
    lot                       TEXT,
    easement                  TEXT,
    building_class            TEXT,
    tax_class                 TEXT,
    building_count            INT,
    dof_square_footage        NUMERIC,
    street_number             TEXT,
    street_name               TEXT,
    zip_code                  TEXT,
    requires_water_data       BOOLEAN,
    multi_building_lot_flag   TEXT,
    source_file               TEXT NOT NULL,
    loaded_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
