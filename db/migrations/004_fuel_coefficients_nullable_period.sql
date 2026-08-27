-- 004_fuel_coefficients_nullable_period.sql
-- Not every fuel-coefficient table is organized by compliance period — a
-- general combustion-fuel list (e.g. butane, kerosene, propane) applies
-- uniformly across periods, unlike utility electricity/gas coefficients.
-- Confirmed live: extraction correctly returned null rather than inventing a
-- period, which then violated the original NOT NULL constraint.

ALTER TABLE fuel_coefficients ALTER COLUMN period_start DROP NOT NULL;
ALTER TABLE fuel_coefficients ALTER COLUMN period_end DROP NOT NULL;
