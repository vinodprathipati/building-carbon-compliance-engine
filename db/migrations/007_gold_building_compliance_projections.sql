-- 007_gold_building_compliance_projections.sql
-- Gold-layer serving table: per-building, per-compliance-period LL97
-- projection. One row per (property_id, period_start, period_end), built
-- by joining a disclosure filing (disclosure_pipeline Silver) against the
-- regulation reference tables (regulation_pipeline extraction output:
-- fuel_coefficients, emissions_factors, penalty_rules, covered_buildings).
--
-- actual_emissions_tco2e is the recalculated figure (fuel use × LL97's own
-- coefficients), NOT the disclosure CSV's Portfolio-Manager-computed
-- Total GHG Emissions column — the two differ by a median of ~4% and can
-- flip a building's compliance verdict entirely.
--
-- Flat carry-forward methodology: actual_emissions_tco2e holds the
-- building's single reported year's fuel usage, applied unchanged against
-- each future period's stricter cap — not a usage forecast.
--
-- Only covered buildings get rows here — a building's BBL must be on
-- DOF's own covered_buildings list, or (fallback, for BBLs not on that
-- list) its GFA must exceed the statutory single-building threshold.
-- Buildings that aren't covered are omitted entirely, not included with a
-- "not covered" status.
--
-- status: 'compliant' | 'exceeds' | 'cap_unavailable' (primary_property_type
-- has no matching row in emissions_factors — e.g. a literal "Mixed Use
-- Property" self-selection, which RCNY's cap table doesn't have its own
-- entry for; blended mixed-use caps per Equation 103-14.1 are not yet
-- implemented, so these buildings surface as a visible gap rather than a
-- silently wrong number).

CREATE TABLE gold_building_compliance_projections (
    id                        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    property_id               TEXT NOT NULL,
    bbl                       TEXT,
    property_name             TEXT,
    borough                   TEXT,
    primary_property_type     TEXT,
    gross_floor_area_ft       NUMERIC,
    year_ending               TEXT NOT NULL,
    period_start              INT NOT NULL,
    period_end                INT NOT NULL,
    status                    TEXT NOT NULL,
    cap_tco2e                 NUMERIC,
    actual_emissions_tco2e    NUMERIC,
    reported_emissions_tco2e  NUMERIC,
    excess_emissions_tco2e    NUMERIC,
    penalty_rate_usd_per_ton  NUMERIC,
    potential_penalty_usd     NUMERIC,
    calculation_method        TEXT NOT NULL DEFAULT 'flat_carry_forward',
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (property_id, period_start, period_end)
);
