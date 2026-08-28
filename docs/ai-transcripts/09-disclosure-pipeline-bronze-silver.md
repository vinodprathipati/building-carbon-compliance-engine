# AI transcript — disclosure_pipeline: Bronze and Silver layers

Session continuing from `08-persistence-pipeline-and-code-review.md`, after
the user's go-ahead to move on from regulation_pipeline to disclosure_pipeline.
Goal: ingest the NYC LL97 disclosure CSV through a medallion (Bronze/Silver)
architecture on PySpark + Delta Lake, running locally.

---

## Part 0 — Architecture and local feasibility

**User:** "before we solutioning, I want to talk about strategy and
architecture. Ideally Spark is the best of handling this. I dont have spark
cluster running in my local. This is an assignment for my interview. I want
to demonstrate my skills... Is there some thing i can do in my local."

**Assistant:** Confirmed Spark local mode (`local[*]`) needs no cluster.
Proposed Bronze/Silver locally in Delta Lake, Gold served from Postgres
alongside the existing regulation_pipeline schema.

**User:** "Can we do in delta format?" — confirmed.

Hit a real, unrelated local-environment blocker while validating this:
**Java 25** (the machine's default JDK) breaks Spark's bundled Hadoop code
(`UnsupportedOperationException: getSubject is not supported` — JDK 23+
removed legacy Security Manager APIs Hadoop's `UserGroupInformation` relies
on). Fixed by pointing `JAVA_HOME` at an already-installed Java 21 LTS
(Temurin), both documented in `README.md` and set programmatically in
`disclosure_pipeline/spark_session.py` before SparkSession creation, read
from `.env` via `disclosure_pipeline/config.py`. Live-validated with a
smoke-test Delta write/read round-trip before writing any real pipeline code.

`disclosure_pipeline/config.py` also derives JDBC connection details
(`jdbc_url`/`jdbc_user`/`jdbc_password`) from the same `DATABASE_URL` the
regulation_pipeline side already uses, for the eventual Gold-layer
Spark→Postgres write.

---

## Part 1 — Bronze layer

Design settled up front: raw and source-faithful, every column read as
string (no schema inference), lineage columns added
(`_source_file`, `_source_file_hash`, `_ingested_at`, `_source_row_number`),
partitioned by `year_ending`, idempotent via source-file hash (mirroring
regulation_pipeline's `rag_documents.document_hash` pattern).

`disclosure_pipeline/bronze.py` — `ingest_bronze(spark, csv_path, bronze_path)`.

**Two real bugs found by testing against the actual 89.5MB CSV, not just
small fixtures:**

1. **Embedded newlines broke row alignment.** Several free-text columns
   (owner notes, explanations) contain commas and literal newlines inside
   quoted fields. Without Spark's `multiLine` CSV option, those quoted
   newlines split one logical row into multiple physical "rows," shifting
   every column after the break — `Year Ending` silently filled with
   garbage from unrelated columns instead of erroring, and a naive
   `sorted()` over the resulting values crashed on a stray `None`. Fixed
   with `.option("multiLine", "true").option("escape", '"')`, which also
   fixed row count (29,842, matching the known-correct total).
2. **Column-name sanitization was a denylist, and denylists lose.**
   Parquet/Delta reject spaces and several punctuation characters in column
   names, so Bronze sanitizes source headers (`"Property Id"` →
   `Property_Id`). The first version denylisted specific characters
   (` ,;{}()\n\t=²`) — the CSV then produced `Weather_Normalized_Site_EUI_kBtu/ft`
   with a literal `/` in the middle, because `/` wasn't in the list. Found by
   the user reading the actual duckdb output, not by inspection. Fixed by
   flipping to an allowlist — `[^A-Za-z0-9]+` → `_` — so any future odd
   character (accents, other symbols) degrades safely instead of needing to
   be discovered and added one at a time.

`year_ending` is derived from the CSV's own `Year Ending` column (not
asserted by the caller) and partitioned on; `replaceWhere` scopes each
write to just the years present in that batch, including a defensive
`year_ending IS NULL` branch (SQL's `IN (...)` never matches `NULL`).

Live-validated end to end: 29,842 rows, 253 columns, correct single
`12/31/2021` partition, idempotency confirmed (re-run on an unchanged file
skips). 5 tests in `tests/disclosure_pipeline/test_bronze.py`, plus a
shared session-scoped `spark` fixture in `conftest.py`.

---

## Part 2 — Silver layer

**User confirmed the plan to move to Silver**, but before writing any code,
real data was inspected — and it corrected two assumptions written down in
an earlier project-memory note as if they were settled:

**Dedup was wrong.** The memory said "283 duplicate Property Ids — prefer
the row with real data." Checking the actual 283 pairs: only 106 fit that
pattern. 129 pairs have identical real values in both rows, and 47 have
*different* real values in both — "prefer non-null" can't resolve those at
all. Looking at real pairs (e.g. same building, one row submitted 05/30,
the other 09/22), the pattern was consistent across every sample checked:
these are amended filings, and the row with the **later `Submission_Date`**
is always the corrected one — including the "one row is `Not Available`"
cases, since the correction is also always the later submission. Rule
implemented: `row_number()` over `Window.partitionBy("Property_Id").orderBy(F.desc("submission_ts"))`,
keep rank 1.

**BBL normalization was incomplete.** The memory said "strip dashes to
normalize." Real data also has semicolon-separated multi-lot BBLs (616
rows, e.g. `"1-02235-0029;1-02235-0035"` for a property spanning two tax
lots) and the literal string `"Not Available"` (56 rows). Implemented:
generic `"Not Available"` → null normalization (applies across all columns,
not just BBL — it's Portfolio Manager's standard null sentinel), dash
stripping per segment, split into a `bbl_list` array column with `bbl` as
the first element for simple single-column joins.

**Third bug, found live during the first full-scale run (not anticipated
in the design discussion):** numeric casting crashed on
`SparkNumberFormatException` for the value `"Insufficient access"` — a
second Portfolio Manager null-placeholder string, distinct from
`"Not Available"`, found only on certain utility columns. Rather than
enumerate every possible placeholder string one at a time (the same mistake
as Bronze's original column-sanitization denylist), switched from `cast` to
`try_cast` for all numeric columns — non-numeric input becomes null instead
of crashing the whole job, regardless of what text Portfolio Manager used.

`disclosure_pipeline/silver.py` — `transform_silver(spark, bronze_path, silver_path)`.
Narrows Bronze's 253 columns to the ones actually needed downstream
(identity/location, property type + mixed-use GFA columns, GHG columns, the
fuel-use columns needed for the LL97 emissions calc), all cast to `double`.
Idempotent via a `_bronze_fingerprint` (the sorted, joined set of Bronze's
distinct `_source_file_hash` values) — skips the transform if Silver
already reflects the current Bronze snapshot exactly.

Live-validated: 29,559 rows (29,842 deduped down by the 283 amended
filings), BBL correctly split for 603 multi-lot properties, idempotency
confirmed. 6 tests in `tests/disclosure_pipeline/test_silver.py`.

---

## Outcome

`disclosure_pipeline` now has a working, tested, idempotent Bronze → Silver
pipeline against the real NYC LL97 disclosure CSV, on PySpark local mode +
Delta Lake, no cluster required. 14/14 disclosure_pipeline tests passing.
Gold (join against regulation_pipeline's Postgres reference tables, compute
compliance projections, serve back to Postgres via JDBC) is the next layer,
not yet built as a pipeline module — validated manually against individual
buildings first to prove the methodology before automating it.
