# LL97 Compliance Example: 591 Third Avenue

Worked example of the full LL97 compliance/penalty calculation methodology,
run end-to-end against real pipeline data (disclosure_pipeline Silver +
regulation_pipeline extraction tables in Postgres). Cross-checked against
`gold_building_compliance_projections` (property_id 20583499).

> **Updated**: an earlier version of this example used a flat electricity
> coefficient (0.000288962 tCO2e/kWh) for every period. RCNY 103-14
> actually specifies a lower coefficient for 2030 onward (0.000145
> tCO2e/kWh), extracted afterward. This lowers the exact excess/penalty
> figures for 2030+ substantially — the qualitative conclusion ("breaches
> the cap starting 2030") is unchanged.

## Building

| Field | Value | Source |
|---|---|---|
| Property ID | 20583499 | disclosure_pipeline Silver |
| Address | 591 Third Avenue, Manhattan, 10016 | Silver |
| BBL | 1009197502 | Silver |
| Property type | Multifamily Housing | Silver (`primary_property_type`) |
| Gross floor area | 75,366 sq ft | Silver (`gross_floor_area_ft`) |
| Reporting year | 12/31/2021 | Silver (`year_ending`) |

## Step 1 — Covered-building check

| Rule | Value | Source |
|---|---|---|
| Single-building threshold | 25,000 sq ft | `covered_building_rules` (Postgres, extracted from Admin Code §28-320) |
| This building's GFA | 75,366 sq ft | Silver |
| **Verdict** | **Covered** (75,366 > 25,000) | |

## Step 2 — Actual emissions (recalculated, not the CSV's reported figure)

The disclosure CSV's own `Total GHG Emissions` column is computed by ENERGY
STAR Portfolio Manager using EPA/eGRID factors — not LL97's statutory
methodology. The correct calculation is `Σ(fuel use × LL97's own fuel
coefficient)`, using coefficients extracted into `fuel_coefficients` — and
the electricity coefficient itself changes by period (utility grid
decarbonizes over time), so actual emissions must be recomputed per period,
not held constant.

**2024–2029** (electricity coefficient 0.000288962 tCO2e/kWh):

| Fuel | Calculation (usage × coefficient = emissions) |
|---|---|
| Grid Electricity | 774,647.5 kWh × 0.000288962 tCO2e/kWh = **223.84 tCO2e** |
| Natural Gas | 2,756,397.4 kBtu × 0.00005311 tCO2e/kBtu = **146.39 tCO2e** |
| **Total** | 223.84 + 146.39 = **370.24 tCO2e** |

**2030–2034 onward** (electricity coefficient drops to 0.000145 tCO2e/kWh
— no further utility-coefficient update is codified yet for 2035+, so this
value is carried forward per `fuel_coefficients`' documented fallback):

| Fuel | Calculation (usage × coefficient = emissions) |
|---|---|
| Grid Electricity | 774,647.5 kWh × 0.000145 tCO2e/kWh = **112.32 tCO2e** |
| Natural Gas | 2,756,397.4 kBtu × 0.00005311 tCO2e/kBtu = **146.39 tCO2e** |
| **Total** | 112.32 + 146.39 = **258.72 tCO2e** |

For comparison, the CSV's own reported 2021 figure was **341.4 tCO2e** — an
8.4% difference from the 2024-2029 recalculation, somewhat above the ~4%
median gap measured across the wider dataset between the reported and
recalculated methodologies.

## Step 3 — Emissions cap by compliance period

Cap = gross floor area × per-property-type cap rate (`emissions_factors`,
extracted from RCNY 103-14's property-type table, property type =
"Multifamily Housing").

| Period | Calculation (GFA × cap rate = cap) |
|---|---|
| 2024–2029 | 75,366 sf × 0.00675 tCO2e/sf = **508.7 tCO2e** |
| 2030–2034 | 75,366 sf × 0.003346640 tCO2e/sf = **252.2 tCO2e** |
| 2035–2039 | 75,366 sf × 0.002692183 tCO2e/sf = **202.9 tCO2e** |
| 2040–2049 | 75,366 sf × 0.002052731 tCO2e/sf = **154.7 tCO2e** |

## Step 4 — Compliance verdict and potential penalty per period

Methodology: flat carry-forward — the building's single reported year of
fuel usage (2021) held constant against each period's stricter cap. Penalty
formula: `max(0, actual − cap) × $268/tCO2e` (`penalty_rules`, rule_type =
`excess_emissions`, extracted from Admin Code §28-320.6).

| Period | Cap | Actual | Status | Excess (actual − cap) | Penalty calculation (excess × $268/tCO2e = penalty) |
|---|---|---|---|---|---|
| 2024–2029 | 508.7 tCO2e | 370.24 tCO2e | ✅ Compliant | 370.24 − 508.7 → 0 | $0 |
| 2030–2034 | 252.2 tCO2e | 258.72 tCO2e | ❌ Exceeds | 258.72 − 252.2 = **6.49 tCO2e** | 6.49 × $268 = **~$1,740** |
| 2035–2039 | 202.9 tCO2e | 258.72 tCO2e | ❌ Exceeds | 258.72 − 202.9 = **55.82 tCO2e** | 55.82 × $268 = **~$14,959** |
| 2040–2049 | 154.7 tCO2e | 258.72 tCO2e | ❌ Exceeds | 258.72 − 154.7 = **104.01 tCO2e** | 104.01 × $268 = **~$27,875** |

## Bottom line

Compliant in the current 2024–2029 period, with comfortable headroom
(138.5 tCO2e). **Breaches the cap starting 2030**, with penalty exposure
that grows each period as the cap tightens — from ~$1,740/year in
2030–2034 up to ~$27,875/year by 2040–2049. The lower 2030+ electricity
coefficient softens the exposure considerably compared to a flat-coefficient
estimate, but doesn't eliminate it: this building's natural gas load (146
tCO2e/year, unaffected by grid decarbonization) is the larger driver of the
excess in every period after 2029.

## Caveats

- Uses the single 2021 baseline year available in the dataset; doesn't
  account for any operational/efficiency changes since then. A retrofit,
  electrification, or envelope upgrade before 2030 could materially change
  this outlook — the flat carry-forward here is a "do nothing" baseline,
  not a prediction.
- No utility-coefficient update is codified yet for 2035 onward — the
  2030-2034 electricity/gas coefficients are carried forward as the best
  available estimate, not a confirmed future value.
- Doesn't yet account for RECs/green-power offset deductions (RCNY 103-14
  references an offset mechanism, exact rule not yet traced — see
  `ll97-disclosure-csv-columns` memory).
- `fuel_oil_5_6_use_kbtu` and a few other minor fuel columns have no
  confirmed LL97 coefficient mapping yet (not applicable to this building —
  its only populated fuel columns are electricity and natural gas).
