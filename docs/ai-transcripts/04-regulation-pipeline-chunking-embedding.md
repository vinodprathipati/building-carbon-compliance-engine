# AI transcript — regulation_pipeline implementation (chunking + embedding)

Session continuing from `03-docling-chunking-experiment.md`. Goal: turn the
validated Docling parsing/chunking approach into real, tested code, and set
the repo up as a proper Python project.

---

**User:** let's implement docling_hybrid_chunker first and pgvector_embedder.
Also convert this to proper python project. pyproject.toml and .env file and
unit test cases also

**User (immediately after, on folder layout):** i want two separate folders
for 2 separate pipelines. one for AI pipeline and another for data pipeline..
We should use correct folder names

**Assistant:** Proposed `ai_pipeline` / `data_pipeline` first, matching the
vocabulary used throughout prior sessions.

**User:** names or not self explinatory. One pipeline is loading the
regulation data and other one is loading disclosure data

**Assistant:** Renamed to `regulation_pipeline` / `disclosure_pipeline` —
named by what each pipeline loads, not by technique. Created the structure:

```
pyproject.toml
.env / .env.example
regulation_pipeline/
    config.py
    chunking/docling_hybrid_chunker.py
    embedding/pgvector_embedder.py
disclosure_pipeline/          # placeholder, disclosures come later
tests/regulation_pipeline/
    test_docling_hybrid_chunker.py
    test_pgvector_embedder.py
```

One `pyproject.toml` for the whole repo (single project, two internal
packages), `hatchling` build backend, Python 3.11+ (actual venv on 3.14,
matching the pipx Docling install already proven working on this machine).

**Implementation — `docling_hybrid_chunker.py`:**

Verified the exact `docling-core` API before writing code against it (via the
existing pipx docling venv) rather than guessing: `HybridChunker` and
`HuggingFaceTokenizer` are pydantic models (`tokenizer`, `merge_peers`,
`max_tokens` fields); `DocItemLabel` is a `str` subclass so `str(item.label)`
gives clean values like `"text"`/`"table"`; `chunker.contextualize(chunk=...)`
prepends the heading path to the chunk body. Confirmed
`nomic-ai/nomic-embed-text-v1`'s tokenizer loads cleanly via
`transformers.AutoTokenizer` (`BertTokenizerFast`, `model_max_length=8192`).

Design: split `chunk_document(document, document_key, chunker)` — a pure
function taking an already-parsed `DoclingDocument` and a ready-built
`HybridChunker` — from `chunk_pdf(pdf_path, document_key, settings)`, the I/O
wrapper that actually runs `DocumentConverter().convert()`. This makes the
mapping logic (page numbers, `block_type` single-vs-`"mixed"`,
`section`/`section_path` from `chunk.meta.headings`, `raw_text` vs.
`full_text`) unit-testable without needing a real PDF, torch inference, or
network access in tests.

**Implementation — `pgvector_embedder.py`, first pass:**

Initial version used the `ollama` Python client (`Client.embed(model=,
input=)`, verified response shape has an `.embeddings` field) to call a
locally-served `nomic-embed-text` model, with `search_document:` prefixing
per nomic's convention. `get_connection(settings)` centralized
`psycopg.connect()` + `pgvector.psycopg.register_vector()` in one place
rather than scattering that setup across call sites.

Wrote 6 unit tests total (3 chunker, 3 embedder), all using fakes/mocks —
no live Postgres or model inference required to run them. All passed.

**User:** instead of using the local ollama. Can we load the model everytime
when we running embedding.

**Assistant:** Switched the embedding path from the Ollama HTTP API to
loading `nomic-embed-text-v1` in-process via `sentence-transformers`
(`SentenceTransformer(model_id, trust_remote_code=True)`), freshly per call
rather than through a persistent model server. Removed the `ollama`
dependency entirely; updated `embed_chunks`/`embed_and_store` signatures
(dropped the `client` parameter), `config.py` (dropped `ollama_host` /
`ollama_embed_model`, kept `embed_model_hf_id` as the one model identifier
used for both tokenizer and embedding model), `.env`/`.env.example`, and both
the unit tests (mock `SentenceTransformer` class instead of an Ollama client)
and a scratch smoke-test script. All 6 tests still passed after the rewrite.

**Real bugs the smoke test caught (unit tests, being mocked, didn't):**

1. `nomic-embed-text` wasn't actually pulled in Ollama despite the user's
   recollection (`ollama list` showed only `qwen2.5:14b`/`llama3.1:8b`) — moot
   once embeddings moved off Ollama, but was the trigger for that change.
2. `einops` — a genuine missing transitive dependency of nomic's custom
   `trust_remote_code` model. Added to `pyproject.toml`.
3. The `rag_documents_one_active_per_key` unique partial index (designed
   weeks earlier, before any code existed) did its job for real: a failed
   smoke-test run left an orphaned `rag_documents` row, and the constraint
   correctly blocked a second active row for the same `document_key` on
   retry. Required manually cleaning the orphaned row rather than a code fix.

**Verified against real data in `cra_dev`:** ran `chunk_pdf` on
`1_RCNY_103-14.pdf` for real (not the earlier CLI-generated JSON) — produced
39 chunks (vs. 159 in the earlier experiment, confirming the nomic 8192-token
budget meaningfully reduces fragmentation vs. the chunker's 512-token
default). Embedded and stored all 39 into `document_chunks` +
`chunk_embeddings`; confirmed `vector_dims(embedding) = 768`, matching
nomic's dimension.

**New parsing-quality finding from real production output** (distinct from
the earlier CLI JSON spot-checks): chunk 6 (page 12) came out genuinely
garbled — `"Nyor urii o eus t e u t e uid ui h l iby section 643..."` where
clean OCR on page 2 produced the same boilerplate correctly
(`"NOTICE IS HEREBY GIVEN, Pursuant to the authority vested in..."`). Docling
fell back to OCR (RapidOCR, visible in logs) on that page and it did badly.
Not currently a problem — page 12 is boilerplate notice text, not one of the
coefficient tables (all on pp. 40-59) — but confirms OCR quality isn't
uniform across this document and is worth watching once other PDFs
(Boston's) get run through the same pipeline.

---

## Where this leaves off

- `regulation_pipeline/` is a real, tested, working package:
  `chunking/docling_hybrid_chunker.py` and `embedding/pgvector_embedder.py`,
  both with unit tests (6 passing) and validated end-to-end against the real
  `1_RCNY_103-14.pdf` and the real `cra_dev` database.
- Embeddings load `nomic-embed-text-v1` in-process via `sentence-transformers`
  per-call — no Ollama dependency for this pipeline anymore.
- `disclosure_pipeline/` is still just a placeholder package — no code yet.
- The revision-history/redline filtering gap noted in `NOTES.md` is still
  unaddressed in the actual chunker code (confirmed live: chunk 4, page 4,
  visibly contains `"[Deleted material is in brackets.]"` redline text in the
  real stored data) — still deferred, not forgotten.
- `rag_id = 6` in `cra_dev` currently holds a full real run (39 chunks) of
  `1_RCNY_103-14.pdf` under `document_key = "smoke_test_rcny_103-14"`, left
  in place intentionally for review rather than cleaned up.
- Not yet built: the `pipeline_runs`/`pipeline_steps` bookkeeping around an
  actual ingest run (today's code creates a `rag_documents` row manually in
  the smoke-test script, not through any orchestrator), and the extraction
  stage itself (the LLM-based factor/penalty extraction from chunks).
