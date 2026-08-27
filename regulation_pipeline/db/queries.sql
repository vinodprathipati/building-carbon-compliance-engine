-- All SQL for regulation_pipeline in one place, looked up by name via
-- regulation_pipeline/db/queries.py. Keeps SQL out of the Python business
-- logic modules — see CLAUDE.md's "No inline SQL" convention.

-- ── Pipeline bookkeeping (rag_documents / pipeline_runs / pipeline_steps) ────

-- name: select_active_rag_document
select rag_id, document_hash, version_id
from rag_documents
where document_key = %s and active_flag
order by version_id desc
limit 1

-- name: deactivate_rag_document
update rag_documents set active_flag = false where rag_id = %s

-- name: insert_rag_document
insert into rag_documents (document_key, document_hash, embed_model, version_id, active_flag)
values (%s, %s, %s, %s, true)
returning rag_id

-- name: update_rag_document_chunk_count
update rag_documents set chunk_count = %s where rag_id = %s

-- name: insert_pipeline_run
insert into pipeline_runs (status, force_regen, doc_type, started_at)
values ('running', %s, %s, now())
returning id

-- name: update_pipeline_run
update pipeline_runs
set status = %s, error = %s, rag_id = %s, completed_at = now()
where id = %s

-- name: insert_pipeline_step
insert into pipeline_steps (run_id, step_name, status, started_at)
values (%s, %s, 'running', now())
returning id

-- name: update_pipeline_step_failed
update pipeline_steps
set status = 'failed', error = %s, duration_ms = %s, completed_at = now()
where id = %s

-- name: update_pipeline_step_success
update pipeline_steps
set status = 'success', meta = %s, duration_ms = %s, completed_at = now()
where id = %s

-- ── Embedding storage (document_chunks / chunk_embeddings / document_tables) ─

-- name: insert_document_chunk
insert into document_chunks
    (rag_id, chunk_id, document_key, page_number, block_type,
     section, section_path, raw_text, full_text, chunk_meta)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)

-- name: insert_chunk_embedding
insert into chunk_embeddings (rag_id, chunk_id, embedding, model_name)
values (%s, %s, %s, %s)

-- name: insert_document_table
insert into document_tables
    (rag_id, table_ref, chunk_id, page_number, caption, column_headers, rows)
values (%s, %s, %s, %s, %s, %s, %s)

-- ── Extraction (retrieval read + persistence writes) ─────────────────────────

-- name: search_chunks
select dc.chunk_id, dc.page_number, dc.block_type, dc.section, dc.raw_text, dc.full_text,
       dc.chunk_meta, 1 - (ce.embedding <=> %s::vector) as similarity
from chunk_embeddings ce
join document_chunks dc using (rag_id, chunk_id)
where ce.rag_id = %s
order by ce.embedding <=> %s::vector
limit %s

-- name: select_document_table_rows
select rows from document_tables where rag_id = %s and chunk_id = %s

-- name: insert_emissions_factor
insert into emissions_factors
    (rag_id, chunk_id, jurisdiction, property_type, period_start, period_end,
     value, unit, extracted_quote, extraction_model)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (rag_id, jurisdiction, property_type, period_start, period_end) do nothing

-- name: insert_fuel_coefficient
insert into fuel_coefficients
    (rag_id, chunk_id, jurisdiction, fuel_type, period_start, period_end,
     value, unit, extracted_quote, extraction_model)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (rag_id, jurisdiction, fuel_type, period_start, period_end) do nothing

-- name: insert_penalty_rule
insert into penalty_rules
    (rag_id, chunk_id, jurisdiction, rule_type, period_start, period_end,
     rate, rate_unit, formula_description, extracted_quote, extraction_model)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (rag_id, chunk_id, jurisdiction, rule_type) do nothing

-- name: insert_covered_building_rule
insert into covered_building_rules
    (rag_id, chunk_id, jurisdiction, threshold_type, threshold_sf,
     aggregation_rule, exceptions, extracted_quote, extraction_model)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
on conflict (rag_id, chunk_id, jurisdiction, threshold_type) do nothing
