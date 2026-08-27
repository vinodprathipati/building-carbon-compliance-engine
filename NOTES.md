# Development notes

## Deferred: revision-history filtering during ingest

`1_RCNY_103-14.pdf` bundles older amendment "Notice of Adoption" redline
sections (deleted text in literal `[brackets]`, added text underlined with no
recoverable marker) ahead of the final rule text. Confirmed via Docling JSON:
bracket markup appears only on pages 4-38, and every table we care about
(42-50) is on a page with zero bracket occurrences — so the current rule text
starts cleanly at the final `§103-14 Requirements for Reporting...` section
header (page 38) with no redline contamination in the tables themselves.

Checked whether Docling could detect this generically: no. It has no
revision/track-changes concept, and its `formatting` field (which could in
principle carry underline/bold styling) is unpopulated on all 553 text
elements with the default `docling_parse` backend — not usable as a signal.

**Decision: not implemented yet.** 
1) When we build ingest, skip chunking pages
before the final occurrence of a document's own top-level section header,
rather than a hardcoded page number — keeps it generic across source PDFs
instead of RCNY-specific. Revisit at that point.

2) Inline SQLs separation

