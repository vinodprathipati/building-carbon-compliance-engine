# CRE Regulations Data Extraction

Pipelines for ingesting municipal building performance standards (e.g., NYC
LL97 / 1 RCNY § 103-14, Boston BERDO) regulation PDFs and building disclosure
filings, to compute per-building compliance/penalty projections.

- `regulation_pipeline/` — parses regulation PDFs, extracts structured
  emissions factors / fuel coefficients / penalty rules / covered-building
  rules via a RAG + LLM extraction pipeline, persists to Postgres.
- `disclosure_pipeline/` — loads building disclosure filings (medallion
  architecture: Delta Lake Bronze/Silver, Postgres Gold), joins against
  `regulation_pipeline`'s extracted rules to compute compliance/penalty
  projections.

## Prerequisites

### 1. Java 21 (required for `disclosure_pipeline` — PySpark + Delta Lake)

**Check this first.** This machine's default Java may be too new for Spark's
bundled Hadoop code — JDK 23+ removed legacy Security Manager APIs Hadoop
still relies on, which surfaces as:

```
java.lang.UnsupportedOperationException: getSubject is not supported
```

Check what's installed:

```
/usr/libexec/java_home -V
```

If a `21.x` entry isn't listed, install one, e.g.:

```
brew install --cask temurin@21
```

Then point `JAVA_HOME` at it in whatever shell/session runs
`disclosure_pipeline` code (path may differ — use the path from the command
above):

```
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home
```

### 2. Postgres with pgvector, running locally

`regulation_pipeline` needs a local Postgres instance reachable at the URL in
`.env` (default expects a database named `cra_dev`), with the `pgvector`
extension available at the server level — not just as a Python package. It
comes bundled with Postgres.app, or install via `brew install pgvector` for a
Homebrew Postgres. The migrations enable it with
`CREATE EXTENSION IF NOT EXISTS vector;`.

```
createdb cra_dev
```

### 3. Python 3.11+

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 4. Environment variables

Copy `.env.example` to `.env` and fill in:
- `DATABASE_URL` — your local Postgres connection string
- `ANTHROPIC_API_KEY` — required for `regulation_pipeline`'s LLM extraction step

## Setup

1. Apply database migrations, in order:
   ```
   for f in db/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
   ```
2. Run tests:
   ```
   .venv/bin/pytest
   ```

## Project layout

- `regulation_pipeline/` — regulation PDF → structured facts (chunking,
  embedding, extraction, persistence; orchestrated end-to-end by `pipeline.py`)
- `disclosure_pipeline/` — building disclosure filings → compliance/penalty
  projections
- `db/migrations/` — Postgres DDL, applied in numeric order
- `db/queries.sql` — every SQL statement used by the pipelines (see
  `CLAUDE.md` for the convention)
- `config/schema/extraction_fields.json` — the field vocabulary driving
  `regulation_pipeline`'s LLM extraction
- `data/raw_pdfs/`, `data/disclosures/` — source documents
- `docs/ai-transcripts/` — development session transcripts
