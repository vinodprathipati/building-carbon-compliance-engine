# LL97 Compliance Example: 527 West 125th Street

Worked example of the full LL97 compliance/penalty calculation methodology,
run end-to-end against real pipeline data (disclosure_pipeline Silver +
regulation_pipeline extraction tables in Postgres). Cross-checked against
`gold_building_compliance_projections` (property_id 12915497).

> **Updated**: an earlier version of this example used a flat electricity
> coefficient (0.000288962 tCO2e/kWh) for every period. RCNY 103-14
> actually specifies a lower coefficient for 2030 onward (0.000145
> tCO2e/kWh) — extracted afterward, once the pipeline could read prose
> facts as well as tables (see `docs/ai-transcripts/`). That correction
> **flips this building's 2040-2049 verdict from "exceeds" to
> "compliant."**

## Building

| Field | Value | Source |
|---|---|---|
| Property ID | 12915497 | disclosure_pipeline Silver |
| Address | 527 West 125th Street, Manhattan, 10027 | Silver |
| BBL | 1019820010 | Silver |
| Property type | Social/Meeting Hall | Silver (`primary_property_type`) |
| Gross floor area | 33,972 sq ft | Silver (`gross_floor_area_ft`) |
| Reporting year | 12/31/2021 | Silver (`year_ending`) |

## Step 1 — Covered-building check

| Rule | Value | Source |
|---|---|---|
| Single-building threshold | 25,000 sq ft | `covered_building_rules` (Postgres, extracted from Admin Code §28-320) |
| This building's GFA | 33,972 sq ft | Silver |
| **Verdict** | **Covered** (33,972 > 25,000) | |

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
| Grid Electricity | 81,265.7 kWh × 0.000288962 tCO2e/kWh = **23.48 tCO2e** |
| Natural Gas | 978,775.8 kBtu × 0.00005311 tCO2e/kBtu = **51.98 tCO2e** |
| **Total** | 23.48 + 51.98 = **75.47 tCO2e** |

**2030–2034 onward** (electricity coefficient drops to 0.000145 tCO2e/kWh
— no further utility-coefficient update is codified yet for 2035+, so this
value is carried forward per `fuel_coefficients`' documented fallback):

| Fuel | Calculation (usage × coefficient = emissions) |
|---|---|
| Grid Electricity | 81,265.7 kWh × 0.000145 tCO2e/kWh = **11.78 tCO2e** |
| Natural Gas | 978,775.8 kBtu × 0.00005311 tCO2e/kBtu = **51.98 tCO2e** |
| **Total** | 11.78 + 51.98 = **63.77 tCO2e** |

For comparison, the CSV's own reported 2021 figure was **72.4 tCO2e** — a
4.2% difference from the 2024-2029 recalculation, consistent with the ~4%
median gap measured across the wider dataset between the reported and
recalculated methodologies.

## Step 3 — Emissions cap by compliance period

Cap = gross floor area × per-property-type cap rate (`emissions_factors`,
extracted from RCNY 103-14's property-type table, property type =
"Social/Meeting Hall").

| Period | Calculation (GFA × cap rate = cap) |
|---|---|
| 2024–2029 | 33,972 sf × 0.00987 tCO2e/sf = **335.3 tCO2e** |
| 2030–2034 | 33,972 sf × 0.003833108 tCO2e/sf = **130.2 tCO2e** |
| 2035–2039 | 33,972 sf × 0.002874831 tCO2e/sf = **97.7 tCO2e** |
| 2040–2049 | 33,972 sf × 0.001916554 tCO2e/sf = **65.1 tCO2e** |

## Step 4 — Compliance verdict and potential penalty per period

Methodology: flat carry-forward — the building's single reported year of
fuel usage (2021) held constant against each period's stricter cap. Penalty
formula: `max(0, actual − cap) × $268/tCO2e` (`penalty_rules`, rule_type =
`excess_emissions`, extracted from Admin Code §28-320.6).

| Period | Cap | Actual | Status | Excess (actual − cap) |
|---|---|---|---|---|
| 2024–2029 | 335.3 tCO2e | 75.47 tCO2e | ✅ Compliant | 75.47 − 335.3 → 0 |
| 2030–2034 | 130.2 tCO2e | 63.77 tCO2e | ✅ Compliant | 63.77 − 130.2 → 0 |
| 2035–2039 | 97.7 tCO2e | 63.77 tCO2e | ✅ Compliant | 63.77 − 97.7 → 0 |
| 2040–2049 | 65.1 tCO2e | 63.77 tCO2e | ✅ Compliant | 63.77 − 65.1 → 0 (1.34 t headroom) |

## Bottom line

**Compliant across every compliance period through 2049**, including a
close-but-clear margin in the final 2040-2049 period (1.34 tCO2e of
headroom). The lower 2030+ electricity coefficient more than offsets the
period's stricter cap for this building. No LL97 penalty exposure under
the flat carry-forward assumption.

## Caveats

- Uses the single 2021 baseline year available in the dataset; doesn't
  account for any operational/efficiency changes since then.
- No utility-coefficient update is codified yet for 2035 onward — the
  2030-2034 electricity/gas coefficients are carried forward as the best
  available estimate, not a confirmed future value.
- Doesn't yet account for RECs/green-power offset deductions (RCNY 103-14
  references an offset mechanism, exact rule not yet traced — see
  `ll97-disclosure-csv-columns` memory).
- `fuel_oil_5_6_use_kbtu` and a few other minor fuel columns have no
  confirmed LL97 coefficient mapping yet (not applicable to this building —
  its only populated fuel columns are electricity and natural gas).
