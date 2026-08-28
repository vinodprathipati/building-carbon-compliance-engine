-- 008_gold_building_fuel_mix.sql
-- Raw fuel usage, passed straight through from disclosure_pipeline Silver
-- with no calculation applied — for the Streamlit UI's fuel-mix pie chart.
-- Deliberately NOT converted to emissions (that's what
-- actual_emissions_tco2e already is) — this is just "what the CSV says
-- this building used," in each fuel's own native unit. Same value on
-- every period row for a given property_id (this doesn't vary by
-- compliance period); mild denormalization, acceptable for a serving
-- table where every row is already one read away from the UI.

ALTER TABLE gold_building_compliance_projections
    ADD COLUMN electricity_use_kwh      NUMERIC,
    ADD COLUMN natural_gas_use_kbtu     NUMERIC,
    ADD COLUMN fuel_oil_1_use_kbtu      NUMERIC,
    ADD COLUMN fuel_oil_2_use_kbtu      NUMERIC,
    ADD COLUMN fuel_oil_4_use_kbtu      NUMERIC,
    ADD COLUMN fuel_oil_5_6_use_kbtu    NUMERIC,
    ADD COLUMN diesel_2_use_kbtu        NUMERIC,
    ADD COLUMN propane_use_kbtu         NUMERIC,
    ADD COLUMN district_steam_use_kbtu  NUMERIC;
