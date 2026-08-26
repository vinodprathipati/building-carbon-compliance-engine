# AI transcript — extraction field schema design

Session continuing from `05-table-extraction-strategy.md`. Goal: design the
JSON field vocabulary that will drive the (not-yet-built) extraction stage —
turning retrieved chunks/tables into rows for the four deferred tables in
`datamodel.md` (`emissions_factors`, `fuel_coefficients`, `penalty_rules`,
`covered_building_rules`).

---

**User:** shared a reference file from another project —
`cat-deal-data-extractor/config/schema/taxonomy.json` — a CAT bond field
vocabulary, noting the name "taxonomy" might not be accurate for what it
actually is. Asked the assistant to understand it first.

**Assistant:** Read the full file and distilled the pattern: it's explicitly
a vocabulary, not a data model (relationships live in a separate
`ontology.json`); concepts nest (top-level concepts hold `fields[]` plus
`subConcepts{}` and repeated collections like `lossClaims[]`, each with their
own `jsonPath`); fields carry rich LLM-facing `description`s (disambiguation
rules, unit-normalization instructions, fallback behavior) rather than just a
type label; a `retrievalHint` field per concept/collection is a keyword-dense
phrase used to drive RAG retrieval before extraction runs — separate from the
field's own description; `derived`/`formula` marks computed (not extracted)
fields; collections document a `naturalKey` for matching rows across
multiple documents over time; `categories` (`static` vs `lifecycle`) group
fields by which document type sources them.

Confirmed the user's suspicion — even the reference file's own description
says "vocabulary, not a data model," so "taxonomy" undersells it. Proposed
adapting the pattern to our four deferred concepts, reusing `retrievalHint`
as literally the same queries already validated empirically in the earlier
vector-search experiment.

**User:** "what are the key fields that we need in these files to calculate
the projections for each building and to classify it is compliant or not?"

**Assistant:** Grounded the field list in the actual downstream calculation
(documented in memory from early in this project): `penalty = max(0,
actual_emissions − allowed_limit) × penalty_rate`, where `actual_emissions =
Σ(fuel_use × fuel_coefficient)` and `allowed_limit = property_type_factor ×
GFA`. Walked through why each field is load-bearing:

- `EmissionsFactor`/`FuelCoefficient` need `period_start`/`period_end` per
  row specifically because projections mean picking a *different* row per
  target year, not recomputing the same one — a building's actual
  consumption can be held constant, but the allowed limit and coefficients
  change per compliance period.
- `FuelCoefficient.unit` matters more than it looks: electricity is
  `tCO2e/kWh`, other fuels are `tCO2e/kBtu` — silently assuming one unit
  across all fuel types would corrupt the calc.
- `PenaltyRule.rule_type` needs to distinguish `excess_emissions` (per-building
  over-cap $, what a projection computes) from `late_filing`/`false_reporting`
  (apply to buildings that never filed at all — a disclosure-pipeline
  join against the covered-buildings list, not this schema).
- `PenaltyRule.formula_description` should capture that NYC's statute caps
  the penalty as "not more than" the calculated amount — a ceiling under
  discretion, not a guaranteed fixed charge; a modeling choice worth being
  explicit about rather than silently assumed.
- `CoveredBuildingRule` needs more than one threshold (single-building vs.
  multi-building-tax-lot) plus `exceptions`, since a building over the sf
  threshold can still be exempt.

Also flagged: compliance classification is a decision chain, not one lookup
(covered? → filed? → actual vs. limit), and the projection-methodology
question (flat carry-forward vs. trend vs. user-adjustable) from very early
in this project is still genuinely unresolved — doesn't block this schema,
but will matter once the disclosure pipeline actually uses these rows.

**User:** confirmed this is downstream/disclosure_pipeline territory, and
clarified they're specifically trying to pin down what to extract from the
regulation PDFs right now.

**Assistant:** Distilled the discussion into a concrete, capped field list
per concept (max 6 fields each), explicitly excluding lineage columns
(`source_chunk_id`, `extracted_quote`, `extraction_model`, `extracted_at`)
from the field list since those aren't extracted content, they're how the
pipeline verifies what got extracted.

**User:** confirmed the field set, asked for an initial JSON draft.

**Assistant:** Wrote `config/schema/extraction_fields.json` (named for what
it is, not "taxonomy," per the user's own flag). Four concepts —
`EmissionsFactor`, `FuelCoefficient`, `PenaltyRule`, `CoveredBuildingRule` —
each with `description`, `jsonPath`, `naturalKey`, `retrievalHint`, and
`fields[]`. Added one thing not explicitly discussed but directly grounded in
the two-strategy pipeline already built: an `extractionMethod` per concept
(`"table"` for `EmissionsFactor`/`FuelCoefficient`, routing to the
deterministic `document_tables` path; `"prose"` for
`PenaltyRule`/`CoveredBuildingRule`, routing to LLM extraction over
`document_chunks` text, since those are statutory sentences with no
underlying table). Field descriptions carry extraction guidance learned the
hard way this session — e.g. `value`: preserve every significant digit,
rounding changes downstream penalty math; `unit` on `FuelCoefficient`: varies
per row within the same table, never assume it matches. Validated as
well-formed JSON.

---

## Where this leaves off

- `config/schema/extraction_fields.json` exists and is agreed — the field
  vocabulary for all four extraction concepts, ready to drive prompt
  construction for the extraction stage.
- **Not yet built:** the extraction stage itself (retrieval → LLM
  confirm/extract → persist). This was about to start
  (`regulation_pipeline` needs an `anthropic` SDK dependency and an API key,
  neither confirmed present yet) when the user asked to pause and export this
  schema-design session first.
- **Not yet built:** the actual `emissions_factors`/`fuel_coefficients`/
  `penalty_rules`/`covered_building_rules` DDL — `datamodel.md` still lists
  these as deferred. The field list is locked, but no migration has been
  written yet.
- The projection-methodology question (flat carry-forward vs. trend vs.
  user-adjustable) remains open from very early in this project — noted
  again here, still not decided.
