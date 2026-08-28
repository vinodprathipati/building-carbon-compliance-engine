# Building Carbon Compliance Engine

Two pipelines and a UI that turn NYC's Local Law 97 — a 60-page DOB rule, a
legal code, and a 260-column disclosure CSV — into a per-building
compliance verdict and penalty projection a non-specialist can act on in
seconds.

## Why this problem

Building performance laws like LL97 create real, escalating financial
exposure — penalties that start in 2024 and get stricter on a fixed
schedule through 2050 — and that exposure directly affects what a
building is worth to buy, sell, or hold. But the source material is
scattered across a statute, an implementing rule that amends it in
non-obvious ways, and a benchmarking export never meant to be read
building-by-building. Someone evaluating an acquisition or a listing
shouldn't need to be a regulatory analyst to get a fast, defensible answer
to "is this building compliant, and what's it going to cost if not."

That's who this is for: a CRE broker or analyst sizing up a specific
property, and — since the underlying pipeline scales to every covered
building in the city, not just one — a portfolio or compliance team
wanting the same answer across a whole book of properties at once.

I picked this over a narrower option because it has two genuinely
different hard problems in it — extracting reliable facts from dense,
inconsistently-formatted regulatory text, and building correct, testable
data engineering at real scale (30k+ disclosure filings, 24k+ covered
buildings) — which felt like a better vehicle to show range than either
alone.

## What the research surfaced

A few things only became clear by actually reading the source documents
and cross-checking the data, not by assuming the obvious path was right:

- **The disclosure CSV's own "Total GHG Emissions" column isn't the
  legally correct number.** It's computed by ENERGY STAR Portfolio
  Manager using EPA/eGRID factors — a different methodology from what
  LL97 actually requires (fuel use × the law's own fixed coefficients).
  The two differ by a median of ~4% across the dataset, and for some
  buildings the difference is large enough to flip the compliance verdict
  entirely in either direction. Using the "obvious" column would have
  been confidently wrong for real buildings.
- **The two source PDFs aren't interchangeable, and the split is
  deliberate.** The Admin Code (the statute) hardcodes only the five
  fuels that cover ~99% of the building stock directly into law, then
  explicitly delegates everything else — and, as it turned out, the
  *updated* 2030-2034 utility coefficients — to the DOB's implementing
  rule (RCNY 103-14). Getting a complete fuel-coefficient table required
  reading both documents and understanding *why* facts are split between
  them, not just pattern-matching on one.
- **Some genuinely tabular regulatory content isn't a table by the time
  it reaches the extraction pipeline.** Docling's table detection is
  good but not complete — depending on page layout, the same kind of fact
  (a coefficient table) sometimes renders as flowing paragraph text. An
  extraction path that only looks for tables silently misses real,
  material facts (the 2030-2034 electricity coefficient, in this case)
  with no error and no signal that anything was missed.
- **A single LLM call asked to find every match across several candidates
  under-reports, reliably.** This surfaced independently in two different
  extraction paths (table matching and prose extraction) — in both cases,
  isolating to one call per candidate fixed it, and batching it back up
  brought the bug back immediately and reproducibly.
- **NYC's own official covered-buildings list doesn't perfectly overlap
  with who actually filed.** There's real drift in both directions
  (buildings on the list that never filed; buildings that filed but
  aren't on the list) — worth knowing before treating either source as
  ground truth on its own.

## How I decided what was worth building

Given how open-ended the assignment is, I chose depth over breadth:
one jurisdiction (NYC LL97), built correctly end-to-end, rather than
partial coverage across NYC and Boston. A half-correct penalty number is
worse than no number for something this financially consequential.

Within that scope, I built in layers with a hard rule: **before any
calculation became pipeline code, I validated it by hand against real
buildings first.** Every methodology decision — recalculated vs. reported
emissions, the flat carry-forward projection, the covered-building
threshold logic — got worked out longhand for one or two actual buildings
before being generalized, and those hand calculations became the
regression tests for the automated version.

I also deliberately left some things unmodeled rather than guess at them:
blended caps for mixed-use buildings (RCNY's Equation 103-14.1), the
separate late-filing penalty for buildings that never disclosed at all,
and RECs/green-power offset deductions. Each of these shows up as an
explicit, visible gap in the output (`cap_unavailable`, or simply not
covered by the current disclosure-based pipeline) rather than a silently
wrong number.

## Assumptions and tradeoffs

- **Flat carry-forward projection.** A building's one reported year of
  fuel usage is held constant and compared against each future
  compliance period's stricter cap/coefficients. This is explicitly a
  "no retrofit, no efficiency gain" baseline, not a usage forecast — the
  conservative framing that's actually useful for a sale-risk
  conversation, and the only one defensible without additional data.
- **Carry forward the most recent codified fuel coefficient** for
  compliance periods the regulation hasn't set a value for yet (2035
  onward, as of this writing) rather than treating that fuel's
  contribution as zero. Reusing a known-real number is closer to correct
  than silently dropping it.
- **DOF's own covered-buildings list is the primary signal for coverage**,
  with the >25,000 sf statutory threshold as a fallback for BBLs not on
  that list — trusts the authoritative source first, falls back to the
  rule computed from raw data second.
- **Different uniqueness rules for table-sourced vs. prose-sourced
  facts.** A fact from a table gets a tight natural-key constraint (each
  fact genuinely lives in one place in a table); a fact from prose gets a
  looser per-chunk constraint, because prose facts are legitimately
  restated at multiple points in a document, and a tight constraint would
  silently pick an arbitrary winner among possibly-conflicting
  extractions with no visibility that a conflict happened.

## Architecture and technical decisions

![Architecture diagram: two independently-built pipelines — regulation_pipeline's RAG extraction and disclosure_pipeline's medallion Bronze/Silver flow — converge at a single Gold Postgres table, which the Streamlit UI reads directly](docs/diagrams/architecture_diagram.png)

*Two independently-built pipelines converge exactly once, at a single Gold
table — the UI never touches Spark or the RAG pipeline directly.*

**`regulation_pipeline`** — regulation PDF → structured facts, via RAG:
Docling parses each PDF with two chunking strategies (general prose, plus
a custom table-descriptor traversal — naively chunking a dense multi-row
table destroys retrieval quality); `nomic-embed-text-v1` runs in-process
via `sentence-transformers` and embeddings land in `pgvector`; Claude does
candidate classification and field extraction. What gets extracted and
how is driven entirely by a JSON field vocabulary
(`config/schema/extraction_fields.json`) — fixing a real extraction bug
(two regulatory concepts being confused with each other) was a schema
edit, not a code change.

**`disclosure_pipeline`** — building disclosures → compliance
projections, via a medallion architecture: PySpark local mode + Delta
Lake for Bronze (raw, source-faithful) and Silver (typed, deduped,
cleaned), Postgres as the Gold/serving layer where both pipelines'
output gets joined into per-building, per-period projections.

**Conventions held across both**: no inline SQL, no inline LLM prompts —
each lives in its own file, loaded by name, so what a query or a prompt
actually says is reviewable in one place rather than scattered through
`.py` files.

**Streamlit UI** reads only from the Gold Postgres table — no Spark
dependency at request time, so the page stays fast and simple to run.

## What I built

- Extraction of 4 regulatory concepts (emissions caps by property type,
  fuel coefficients, penalty rules, covered-building thresholds) from 2
  source PDFs, cross-referenced against each other where the law splits
  facts between them.
- A one-time load of NYC DOF's official covered-buildings list (24,135
  BBLs) parsed directly from its PDF.
- Bronze → Silver → Gold processing of the full NYC LL97 disclosure CSV:
  29,842 filed rows deduped to 29,559 buildings, 28,030 of them
  confirmed covered, projected across 4 compliance periods each —
  112,120 compliance/penalty rows, computed with the corrected
  (not-just-reported) emissions methodology.
- A Streamlit app to search any covered building by Property ID and see
  its fuel mix, compliance status, and penalty exposure through 2049 —
  no Spark needed to view it.
- ~85 tests covering the calculation logic, extraction reliability fixes,
  and pipeline orchestration, plus dev-log transcripts of the design
  decisions in `docs/ai-transcripts/`.

## What I'd change or build next

- **Mixed-use blended caps** (Equation 103-14.1) — these buildings
  currently surface as `cap_unavailable` rather than a computed number;
  the blending logic itself isn't implemented yet.
- **Non-filer / late-filing penalties** — a different penalty mechanism
  (per-sf-per-month) applies to covered buildings that never disclosed at
  all; the current pipeline only scores buildings that did file.
- **RECs / green-power offset deductions** — RCNY references an offset
  mechanism for renewable energy that isn't wired into the actual-emissions
  calculation yet.
- **Boston BERDO** — the architecture is already jurisdiction-parameterized
  throughout Gold's reference-data loaders; no Boston-specific documents
  have been extracted yet, but adding the second jurisdiction shouldn't
  require re-architecting anything.
- **Extend the per-candidate extraction reliability fix everywhere it
  applies** — it's currently only wired into the table-concept routing
  path; the standalone prose-concept path (penalty rules, covered-building
  rules) still batches multiple candidates into one call.
- **Real deployment** — the UI currently only runs locally; a hosted
  version with basic auth would be the natural next step for actual team
  use.

---

## Getting started

### Prerequisites

**1. Java 21** (required for `disclosure_pipeline` — PySpark + Delta
Lake). Check this first — a too-new default JDK breaks Spark's bundled
Hadoop code:
```
/usr/libexec/java_home -V
```
If no `21.x` entry is listed:
```
brew install --cask temurin@21
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home
```

**2. Postgres with pgvector**, running locally, reachable at the URL in
`.env`. `pgvector` needs to be available at the server level (bundled
with Postgres.app, or `brew install pgvector` for a Homebrew Postgres):
```
createdb cra_dev
```

**3. Python 3.11+**
```
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

**4. Environment variables** — copy `.env.example` to `.env` and fill in
`DATABASE_URL` and `ANTHROPIC_API_KEY`.

### Setup

```
for f in db/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
.venv/bin/pytest
```

### Clean end-to-end run

```
# 1. Reset
psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
for f in db/migrations/*.sql; do psql "$DATABASE_URL" -f "$f"; done
rm -rf data/lake

# 2. regulation_pipeline (both PDFs — fuel_coefficients draws from both)
.venv/bin/python scripts/run_regulation_pipeline.py

# 3. Covered buildings list (one-time, not a pipeline)
.venv/bin/python scripts/load_covered_buildings_list.py

# 4. disclosure_pipeline: Bronze -> Silver -> Gold
.venv/bin/python scripts/run_disclosure_pipeline.py
```
Step 2 makes real, billed Anthropic API calls and can take several
minutes; step 4 processes the full ~30k-row disclosure CSV through Spark.

### Run the UI

```
.venv/bin/streamlit run streamlit_app.py
```

## Project layout

- `regulation_pipeline/` — regulation PDF → structured facts (chunking,
  embedding, extraction, persistence; orchestrated end-to-end by `pipeline.py`)
- `disclosure_pipeline/` — building disclosure filings → compliance/penalty
  projections (`bronze.py` / `silver.py` / `gold.py`)
- `streamlit_app.py` — the building-search UI
- `db/migrations/` — Postgres DDL, applied in numeric order
- `regulation_pipeline/db/queries.sql` — every SQL statement `regulation_pipeline`
  uses (see `CLAUDE.md` for the convention)
- `config/schema/extraction_fields.json` — the field vocabulary driving
  `regulation_pipeline`'s LLM extraction
- `scripts/` — one-off/orchestration scripts (full pipeline runs, the
  covered-buildings one-time load)
- `data/raw_pdfs/`, `data/disclosures/` — source documents
- `docs/ai-transcripts/` — development session transcripts
- `docs/examples/` — hand-worked compliance examples used as ground truth
  for the automated calculation
