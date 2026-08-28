# LL97 Compliance Example: 527 West 125th Street

Worked example of the full LL97 compliance/penalty calculation methodology,
run end-to-end against real pipeline data (disclosure_pipeline Silver +
regulation_pipeline extraction tables in Postgres).

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
coefficient)`, using coefficients extracted into `fuel_coefficients`.

| Fuel | Calculation (usage × coefficient = emissions) | Source (jurisdiction = New York City) |
|---|---|---|
| Grid Electricity | 81,265.7 kWh × 0.000288962 tCO2e/kWh = **23.48 tCO2e** | `fuel_coefficients` (Admin Code §28-320.3.1.1, prose) |
| Natural Gas | 978,775.8 kBtu × 0.00005311 tCO2e/kBtu = **51.98 tCO2e** | `fuel_coefficients` (Admin Code §28-320.3.1.1, prose) |
| All other fuel types | 0 (null in Silver) = **0 tCO2e** | — |
| **Recalculated total** | 23.48 + 51.98 + 0 = **75.47 tCO2e** | |

For comparison, the CSV's own reported figure was **72.4 tCO2e** — a 4.2%
difference, consistent with the ~4% median gap measured across the wider
dataset between the reported and recalculated methodologies.

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

| Period | Cap | Actual | Status | Excess (actual − cap) | Penalty calculation (excess × $268/tCO2e = penalty) |
|---|---|---|---|---|---|
| 2024–2029 | 335.3 tCO2e | 75.47 tCO2e | ✅ Compliant | 75.47 − 335.3 → 0 | $0 |
| 2030–2034 | 130.2 tCO2e | 75.47 tCO2e | ✅ Compliant | 75.47 − 130.2 → 0 | $0 |
| 2035–2039 | 97.7 tCO2e | 75.47 tCO2e | ✅ Compliant | 75.47 − 97.7 → 0 | $0 |
| 2040–2049 | 65.1 tCO2e | 75.47 tCO2e | ❌ Exceeds | 75.47 − 65.1 = **10.37 tCO2e** | 10.37 × $268 = **~$2,779** |

## Bottom line

Compliant through 2039, including the current 2024–2029 period. Only
breaches the cap in the 2040–2049 period, and modestly (~$2,779) —
assuming flat energy use two decades out, a conservative worst case rather
than a prediction.

## Caveats

- Uses the single 2021 baseline year available in the dataset; doesn't
  account for any operational/efficiency changes since then.
- Doesn't yet account for RECs/green-power offset deductions (RCNY 103-14
  references an offset mechanism, exact rule not yet traced — see
  `ll97-disclosure-csv-columns` memory).
- `fuel_oil_5_6_use_kbtu` and a few other minor fuel columns have no
  confirmed LL97 coefficient mapping yet (not applicable to this building —
  its only populated fuel columns are electricity and natural gas).
