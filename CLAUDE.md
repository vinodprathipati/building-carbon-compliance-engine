# CRE Regulations Data Extraction

Pipeline for ingesting municipal building performance standards (e.g., NYC LL97 / 1 RCNY § 103-14, Boston BERDO) PDFs.
This pipeline consists of following steps.

## Conventions

**No inline SQL.** Every SQL statement lives in `regulation_pipeline/db/queries.sql`, one file, each statement preceded by a `-- name: query_name` marker. Look it up from Python via `sql("query_name")` (`regulation_pipeline/db/queries.py`) and pass the result straight to `cur.execute(sql("query_name"), params)`. Never write `cur.execute("select ...")` with the SQL inline in a `.py` file — add it to `queries.sql` instead, even for a one-line query.

Why: keeps every query in one place to scan/review at once, gives real SQL syntax (not a Python string), and keeps business-logic modules free of embedded SQL. Deliberately not an ORM — the schema is small and upsert-heavy enough that raw SQL is more direct.

**No inline LLM prompts.** Same pattern, same reason — prompts are content, not logic, and belong out of the `.py` files they're used from. Every prompt template lives in `regulation_pipeline/extraction/prompt_templates.txt`, one file, each template preceded by a `-- name: template_name` marker (same marker convention as `queries.sql` — both are parsed by the shared `regulation_pipeline/text_blocks.py` loader). Templates use Python `str.format()` placeholders (`{concept_name}`, `{full_text}`, etc.); a literal `{`/`}` in the template text itself (e.g. inside a JSON example) must be escaped as `{{`/`}}`. Compute the dynamic pieces (field lists, candidate text blocks, etc.) in Python as before — only the surrounding prompt prose/instructions move to the template file, not the logic that builds each piece.