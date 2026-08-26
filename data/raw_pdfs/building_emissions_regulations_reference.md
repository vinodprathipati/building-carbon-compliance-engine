# Municipal Building Emissions Regulations: Data Source Reference Guide

This reference document outlines the core legislative and technical regulatory files used in the commercial real estate (CRE) building emissions extraction pipeline for **New York City** and **Boston**.

---

## Architectural Pattern: Two-Tiered Municipal Framework

Municipalities govern building emissions through a two-tiered legal and technical structure:

1. **Statutory Law (City Council Ordinance):** Establishes legal authority, definitions for covered buildings, statutory penalty structures, and compliance deadlines.
2. **Technical Regulations (Executive Agency Rules):** Promulgated by city building or environment departments to detail exact building category limits, lookup tables, and fuel carbon intensity conversion factors.

```
                          ┌──► [ Statutory Law (Ordinance) ] ─────► Penalty Rates & Enforcement Fines
                          │
[ Multi-Document Ingest ] ┤
                          │
                          └──► [ Technical Regulations ] ─────────► Property Caps & Fuel Conversion Factors
```

---

## Detailed File Reference Matrix

| File Name | Jurisdiction | Tier / Category | Primary Purpose & Extracted Parameters |
| :--- | :--- | :--- | :--- |
| **`1_RCNY_103-14.pdf`** | New York City | Technical Regulations | **DOB Rule 103-14:** Detailed technical lookup tables for 60+ ENERGY STAR Portfolio Manager property types, precise carbon intensity limits ($	ext{tCO}_2	ext{e/sq ft}$), and fuel emissions factors (electricity, natural gas, steam). |
| **`NYC_AdminCode_Chapter3.pdf`** | New York City | Statutory Law | **NYC Admin Code Title 28, Art. 320 (LL97):** Baseline legislation establishing covered building criteria ($>25,000 	ext{ sq ft}$), statutory penalty rate ($\$268/	ext{metric ton}$ over limit), and late reporting fines ($\$0.50/	ext{sq ft/month}$). |
| **`boston_berdo_regulations.pdf`** | Boston | Technical Regulations | **BERDO Phase 2 Regulations:** Sector-based building carbon limits ($	ext{kgCO}_2	ext{e/sq ft}$) across 5-year compliance intervals ($2025-2029$, $2030-2034$, etc.), fuel conversion factors, and third-party verification rules. |
| **`boston_berdo_ordinance.pdf`** | Boston | Statutory Law | **BERDO 2.0 Ordinance (City Council Docket 0775):** Baseline ordinance establishing daily non-compliance penalties (up to $\$1,000/	ext{day}$ for large covered buildings), hardship provisions, and net-zero target timelines (2050). |

---

## Detailed Summary of Each File

### 1. `1_RCNY_103-14.pdf` — NYC DOB Technical Rule
* **Issuer:** NYC Department of Buildings (DOB)
* **Role in Pipeline:** Primary target for property-level compliance calculations.
* **Key Targets for Extraction:**
  * Property-type emission caps for 2024–2029 and 2030–2034 across 60+ building categories.
  * Greenhouse gas coefficients for delivered energy (grid electricity, natural gas, fuel oil #2/#4, district steam).
  * Deductions for clean electricity and renewable energy certificates (RECs).
* **Pydantic Mapping:** `property_caps`, `fuel_coefficients`

---

### 2. `NYC_AdminCode_Chapter3.pdf` — NYC Statutory Law
* **Issuer:** NYC City Council / American Legal Publishing Code Library
* **Role in Pipeline:** Primary target for statutory enforcement mechanisms and legal definitions.
* **Key Targets for Extraction:**
  * Square footage thresholds defining "covered buildings" (single building $> 25,000	ext{ gsf}$; multiple buildings on single tax lot $> 50,000	ext{ gsf}$).
  * Excess emissions penalty multiplier ($\$268$ per metric ton of $	ext{CO}_2	ext{e}$ above limit).
  * Statutory exceptions, non-profit healthcare adjustments, and affordable housing rules.
* **Pydantic Mapping:** `statutory_penalties`, `covered_building_thresholds`, `statute_reference`

---

### 3. `boston_berdo_regulations.pdf` — Boston Technical Rule
* **Issuer:** City of Boston Environment Department
* **Role in Pipeline:** Primary target for technical emissions evaluation in Boston.
* **Key Targets for Extraction:**
  * Building sector carbon caps expressed in $	ext{kgCO}_2	ext{e/sq ft/year}$.
  * 5-year step-down schedules leading to Net Zero by 2050.
  * Blend rules for mixed-use commercial properties.
* **Pydantic Mapping:** `property_caps`, `emissions_units`, `compliance_intervals`

---

### 4. `boston_berdo_ordinance.pdf` — Boston Statutory Law
* **Issuer:** Boston City Council
* **Role in Pipeline:** Primary target for Boston legal compliance and financial penalty modeling.
* **Key Targets for Extraction:**
  * Daily penalty structure: Up to $\$1,000/	ext{day}$ for major covered structures; $\$300/	ext{day}$ for mid-sized structures.
  * Reporting failure penalties: $\$150–\$300/	ext{day}$.
  * Designation of statutory authority under City of Boston Code, Section 7-2.2.
* **Pydantic Mapping:** `daily_penalty_rates`, `statutory_authority`

---

## Ingestion Architecture & Normalized Artifacts

The extraction engine parses these paired documents per city into normalized JSON artifacts:

```
data/raw_pdfs/
├── 1_RCNY_103-14.pdf ─────────────┐
│                                  ├─► Engine Parser ─► nyc_ll97_rules.json
├── NYC_AdminCode_Chapter3.pdf ────┘
│
├── boston_berdo_regulations.pdf ──┐
│                                  ├─► Engine Parser ─► boston_berdo_rules.json
└── boston_berdo_ordinance.pdf ────┘
```

Each resulting JSON file conforms to a unified `RegulatoryRuleset` Pydantic schema, enabling multi-city scalability.
