# AI transcript — Docling parsing/chunking experiment

Session continuing from `02-ai-extraction-pipeline-datamodel.md`. Goal:
hands-on validation of Docling before writing any pipeline code — parse the
NYC regulation PDFs to JSON, check table/text extraction quality, and work out
a chunking strategy.

---

**User:** Let's focus on parsing part. Before we implement the code. I want to
experiment docling. Docling has CLI util to generate the json file.

**Assistant:** Confirmed Docling CLI (v2.76.0, installed via pipx at
`~/.local/pipx/venvs/docling`) was available. Ran it against
`1_RCNY_103-14.pdf` with `--to json`, first in embedded-image mode (34MB
output), then regenerated with `--image-export-mode placeholder` (1.6MB) once
the user asked to keep the files locally for review — added
`data/processed/docling_json/` to `.gitignore` so they stay local, not pushed.

**User:** Can you also convert NYC_AdminCode_Chapter3.pdf → **Assistant:**
Converted it the same way (1.4MB output, same directory).

**User:** Can you check the parsing quality?

**Assistant:** Cross-checked extracted values against the LL97 facts already
in memory from manual extraction — all matched, on the correct pages, in
clean readable text (native-text PDF, no OCR artifacts):

- Electricity/gas/fuel-oil-#2 coefficients (`0.000288962`, `0.00005311`,
  `0.00007421`) — page 33, list items.
- R-2 occupancy coefficients, 2024-29 (`0.00675`, p.33) and 2030-34
  (`0.00407`, p.34).
- Covered-building `25,000` sf threshold — page 15.
- `$268`/ton penalty formula and `$500,000` false-statement penalty — page 37,
  full sentence extracted cleanly.

Noted a structural difference between the two PDFs: RCNY 103-14 is
table-heavy (26 tables), Admin Code has only 1 table — its coefficients live
in numbered-list prose instead. Flagged this as relevant to the extraction
prompt design (can't assume `block_type == table` universally).

**User:** let's focus on chunking strategy, Can we chunk for each section in
the PDF? I mean group all items under the same section header

**Assistant:** Tested this directly rather than assuming. Walked each
document's body tree:

- **Admin Code** — `section_header` elements map cleanly onto real
  legal provisions (`§ 28-303.2.1 Internal inspection required.`), flat
  `level=1`, small and self-contained. Pure section-based grouping works well.
- **RCNY 103-14** — breaks. The entire operative rule (pp. 38-61, all 26
  tables) sits under a single `section_header` (`§103-14 Requirements for
  Reporting...`, page 38). Grouping strictly by header would produce one
  enormous, unusable chunk.

Ran Docling's own `HybridChunker` against RCNY as the actual fix: it groups by
heading path but caps chunk size by token budget, splitting oversized
sections at natural (row/paragraph) boundaries while keeping the heading path
attached as metadata. Produced 159 chunks from 553 texts + 26 tables. Also
found it serializes tables into row-level natural-language sentences (e.g.
`"Butane, Emissions Coefficient (tCO2e per kBtu) = 0.00006502."`) — so a split
table still yields complete, self-contained facts per chunk, not truncated
cells.

This surfaced a data-quality bug: a chunk from page 5 (inside an amendment
redline notice) contained the same 20-row fuel-coefficient table as the
codified pages 49-50, with matching values in this instance.

Flagged one tuning gap: the default `HybridChunker` tokenizer caps chunks at
512 tokens; `nomic-embed-text-v1` supports up to 8192 — worth pointing the
chunker at nomic's tokenizer so chunks aren't needlessly fragmented.

**User:** I did not get why we need to filter the pages >=36

**Assistant:** Explained the concrete risk: this PDF bundles multiple
"Notice of Adoption" redline packages (bracketed deleted text, underlined
added text — no font styling, literal characters) ahead of the final codified
text. If a redline copy of a clause shows an old, superseded value and the
codified copy shows the current one, plain-text extraction has no way to tell
which is authoritative — risking silently duplicated or conflicting facts.
Acknowledged the one table checked so far matched exactly, so the failure
mode was still theoretical at that point.

**User:** For now let it be, We can change this later. Since there is no
change in the values.. But we will keep it noted and change the
implementation

**Assistant:** Attempted to write this decision into `datamodel.md`; user
redirected mid-investigation instead (see below) before it was committed.

**User:** Which page has bracketed version

**Assistant:** Searched the RCNY JSON for literal `[...]` spans. Found real,
substantive redline diffs at pages 7, 8, 20, 21, 23 — not just page 5's
duplicate table — including a genuine word-level change (`"...excluding]
including any electricity..."`) and an equation renumbering
(`"(Equation [103-14.11] 103-14.13)"`). Also found the redline legend itself
attached to the page-38 section header, which at first looked like it
contradicted the "pp. 36+ is clean" assumption from memory.

**User:** Are these not marked as diffs in PDF file..

**Assistant:** Checked the raw JSON element for the `[excluding] including`
example: no formatting/style metadata on Docling `TextItem`s at all (no
bold/underline/strikethrough flag) — deletions are literal bracket characters
baked into the extracted text, additions are unmarked plain text. This
reframed the fix: stripping `[...]` spans reconstructs the current, in-effect
text regardless of page — content-based, not a page cutoff. Verified this
logic against all found examples (all correct after stripping).

**User:** Can we ignore revision history while parsing

**Assistant:** Re-checked precisely where bracket markup actually stops:
**zero** bracket occurrences anywhere from page 39 onward; the only hit at/after
page 38 is the legend sentence itself, not an actual edit. So the real
boundary is pages 1-38 = revision history, pages 39-61 = clean text with zero
markup — and every table of interest (42-50) is inside the clean zone. This
makes "just don't ingest before the final section" simpler than
bracket-stripping. Asked whether the cutoff should be a hardcoded page number
or detected generically (e.g. "start from the last occurrence of the
document's own top-level section header").

**User:** Does docling has way to ignore the revisions completely..

**Assistant:** Checked directly: no built-in feature — Docling has no
revision/track-changes concept. Its schema does have a `formatting` field
(could carry underline/bold) but it came back unpopulated on all 553 text
elements with the default `docling_parse` backend — not usable as a signal
without testing another backend (`dlparse_v4`/`pypdfium2`), which wasn't done.

**User:** ignore for now. I want to implement a pgvector_embedder and
docling_hybrid_chunker .. keep code clean

**Assistant:** Started scoping the two modules; user asked to pause for a
documentation checkpoint before continuing into implementation. Noted the
revision-history-filtering decision in `NOTES.md` (not `datamodel.md`, per
correction) as a deferred item, and wrote this transcript.

---

## Where this leaves off

- Docling parsing quality is validated on both NYC PDFs (RCNY 103-14, Admin
  Code Chapter 3) against known-correct values from memory — no discrepancies
  found.
- Chunking strategy is settled: use Docling's `HybridChunker` (heading-path +
  token-budget aware), not naive "one chunk per section header" — the latter
  fails badly on RCNY's single-top-level-header structure. Heading path feeds
  `section`/`section_path` in `document_chunks`.
- Revision-history filtering is a known, evidence-backed gap — documented in
  `NOTES.md` — deferred until ingest is actually implemented. Current lean:
  detect the cutoff generically (last occurrence of the doc's own top-level
  section header) rather than hardcoding a page number.
- **Not yet done:** Boston PDFs haven't been run through Docling at all.
- **Next:** implement `docling_hybrid_chunker` (wraps parse + HybridChunker,
  emits chunk records matching the `document_chunks` schema — likely
  `raw_text` = `chunk.text`, `full_text` = `chunker.contextualize(chunk)`) and
  `pgvector_embedder` (embeds via Ollama/`nomic-embed-text-v1` with the
  `search_document:` prefix, writes to `document_chunks` + `chunk_embeddings`
  in `cra_dev`). Environment check (installed packages, project venv) was
  interrupted before completion — still needs doing.
