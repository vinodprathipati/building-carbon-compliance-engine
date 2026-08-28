from __future__ import annotations

from decimal import Decimal

import pytest

from disclosure_pipeline.gold import (
    build_gold_rows,
    compute_actual_emissions,
    compute_compliance_projection,
    compute_emissions_cap,
    is_building_covered,
)

PERIODS = [(2024, 2029), (2030, 2034), (2035, 2039), (2040, 2049)]

FUEL_COEFFICIENTS = {
    "Grid Electricity": [
        {"value": Decimal("0.000288962"), "period_start": 2024, "period_end": 2029},
        {"value": Decimal("0.000145"), "period_start": 2030, "period_end": 2034},
    ],
    "Natural Gas": [
        {"value": Decimal("0.00005311"), "period_start": 2024, "period_end": 2029},
        {"value": Decimal("0.00005311"), "period_start": 2030, "period_end": 2034},
    ],
    "Diesel": [{"value": Decimal("0.00007421"), "period_start": None, "period_end": None}],
}

EMISSIONS_CAPS = {
    "Social/Meeting Hall": [
        {"value": Decimal("0.00987"), "period_start": 2024, "period_end": 2029},
        {"value": Decimal("0.003833108"), "period_start": 2030, "period_end": 2034},
        {"value": Decimal("0.002874831"), "period_start": 2035, "period_end": 2039},
        {"value": Decimal("0.001916554"), "period_start": 2040, "period_end": 2049},
    ],
    "Multifamily Housing": [
        {"value": Decimal("0.00675"), "period_start": 2024, "period_end": 2029},
        {"value": Decimal("0.003346640"), "period_start": 2030, "period_end": 2034},
        {"value": Decimal("0.002692183"), "period_start": 2035, "period_end": 2039},
        {"value": Decimal("0.002052731"), "period_start": 2040, "period_end": 2049},
    ],
}

PENALTY_RATE = Decimal("268")


def test_is_building_covered_true_when_on_covered_list_regardless_of_gfa():
    assert is_building_covered({"gross_floor_area_ft": 1000.0}, Decimal("25000"), is_on_covered_list=True)


def test_is_building_covered_false_below_threshold_and_not_on_list():
    building = {"gross_floor_area_ft": 13770.0}
    assert is_building_covered(building, Decimal("25000"), is_on_covered_list=False) is False


def test_is_building_covered_true_above_threshold_fallback():
    building = {"gross_floor_area_ft": 33972.0}
    assert is_building_covered(building, Decimal("25000"), is_on_covered_list=False) is True


def test_compute_actual_emissions_sums_across_fuels_for_the_target_period():
    building = {"electricity_use_kwh": 81265.7, "natural_gas_use_kbtu": 978775.8}
    actual = compute_actual_emissions(building, FUEL_COEFFICIENTS, 2024, 2029)
    # matches the hand-verified 527 W 125th St example: 23.48 + 51.98 = 75.47
    assert actual == pytest.approx(Decimal("75.4655"), abs=Decimal("0.01"))


def test_compute_actual_emissions_picks_period_scoped_coefficient_not_a_different_period():
    building = {"electricity_use_kwh": 774647.5, "natural_gas_use_kbtu": 2756397.4}
    actual_2024 = compute_actual_emissions(building, FUEL_COEFFICIENTS, 2024, 2029)
    actual_2030 = compute_actual_emissions(building, FUEL_COEFFICIENTS, 2030, 2034)
    assert actual_2024 != actual_2030  # electricity coefficient drops for 2030-2034
    assert actual_2030 < actual_2024


def test_compute_actual_emissions_falls_back_to_null_period_row():
    building = {"diesel_2_use_kbtu": 1000}
    actual = compute_actual_emissions(building, FUEL_COEFFICIENTS, 2035, 2039)
    assert actual == Decimal("1000") * Decimal("0.00007421")


def test_compute_actual_emissions_ignores_missing_and_zero_usage():
    building = {"electricity_use_kwh": None, "natural_gas_use_kbtu": 0}
    assert compute_actual_emissions(building, FUEL_COEFFICIENTS, 2024, 2029) == Decimal(0)


def test_compute_actual_emissions_carries_forward_most_recent_coefficient_beyond_2034():
    # No source coefficient exists yet for 2035-2039/2040-2049 (caps for
    # those periods are codified, but DOB hasn't published updated utility
    # coefficients for them) — carry forward the 2030-2034 value rather
    # than silently treating electricity's contribution as zero.
    building = {"electricity_use_kwh": 1000}
    actual_2035 = compute_actual_emissions(building, FUEL_COEFFICIENTS, 2035, 2039)
    assert actual_2035 == Decimal("1000") * Decimal("0.000145")  # 2030-2034's rate, not zero


def test_compute_actual_emissions_ignores_fuel_with_no_coefficient_data():
    building = {"propane_use_kbtu": 500}  # not present in FUEL_COEFFICIENTS fixture
    assert compute_actual_emissions(building, FUEL_COEFFICIENTS, 2024, 2029) == Decimal(0)


def test_compute_emissions_cap_matches_hand_verified_example():
    cap = compute_emissions_cap("Social/Meeting Hall", 33972.0, EMISSIONS_CAPS, 2024, 2029)
    assert cap == pytest.approx(Decimal("335.3"), abs=Decimal("0.5"))


def test_compute_emissions_cap_none_when_property_type_unmapped():
    assert compute_emissions_cap("Mixed Use Property", 50000.0, EMISSIONS_CAPS, 2024, 2029) is None


def test_compute_emissions_cap_none_when_gfa_missing():
    assert compute_emissions_cap("Multifamily Housing", None, EMISSIONS_CAPS, 2024, 2029) is None


def test_compute_compliance_projection_matches_527_w_125th_st_example():
    # Regression test against the hand-verified worked example
    # (docs/examples/527-w-125th-st-compliance-example.md).
    #
    # NOTE: the markdown example was written using a flat electricity
    # coefficient (0.000288962) across every period. This test uses the
    # period-correct coefficients (electricity drops to 0.000145 for
    # 2030-2034+) discovered afterward — which flips the 2040-2049 verdict
    # from "exceeds" to "compliant" (lower electricity coefficient more
    # than offsets the stricter cap). The markdown doc was updated to match.
    building = {
        "primary_property_type": "Social/Meeting Hall",
        "gross_floor_area_ft": 33972.0,
        "electricity_use_kwh": 81265.7,
        "natural_gas_use_kbtu": 978775.8,
    }

    results = compute_compliance_projection(building, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS)

    by_period = {(r["period_start"], r["period_end"]): r for r in results}
    assert all(r["status"] == "compliant" for r in by_period.values())
    assert by_period[(2040, 2049)]["excess_emissions_tco2e"] == Decimal(0)


def test_compute_compliance_projection_matches_591_third_avenue_example():
    # Regression test against the hand-verified worked example
    # (docs/examples/591-third-avenue-compliance-example.md) — this
    # building breaches the cap starting 2030, unlike the example above.
    # See the note on the 527 W 125th St test above re: the corrected
    # period-specific electricity coefficient changing the exact figures
    # (though not the qualitative "exceeds starting 2030" conclusion here).
    building = {
        "primary_property_type": "Multifamily Housing",
        "gross_floor_area_ft": 75366.0,
        "electricity_use_kwh": 774647.5,
        "natural_gas_use_kbtu": 2756397.4,
    }

    results = compute_compliance_projection(building, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS)
    by_period = {(r["period_start"], r["period_end"]): r for r in results}

    assert by_period[(2024, 2029)]["status"] == "compliant"
    assert by_period[(2030, 2034)]["status"] == "exceeds"
    assert by_period[(2030, 2034)]["potential_penalty_usd"] == pytest.approx(Decimal("1740"), abs=Decimal("5"))
    assert by_period[(2040, 2049)]["status"] == "exceeds"
    assert by_period[(2040, 2049)]["potential_penalty_usd"] == pytest.approx(Decimal("27875"), abs=Decimal("5"))


def test_compute_compliance_projection_reports_cap_unavailable_for_unmapped_property_type():
    building = {
        "primary_property_type": "Mixed Use Property",
        "gross_floor_area_ft": 50000.0,
        "electricity_use_kwh": 100000.0,
    }
    results = compute_compliance_projection(building, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS)
    assert all(r["status"] == "cap_unavailable" for r in results)
    assert all(r["cap_tco2e"] is None for r in results)
    assert all(r["potential_penalty_usd"] is None for r in results)


def test_build_gold_rows_omits_buildings_that_are_not_covered():
    buildings = [
        {
            "property_id": "1",
            "bbl": "9999999999",  # not on covered list
            "primary_property_type": "Social/Meeting Hall",
            "gross_floor_area_ft": 13770.0,  # below threshold too
            "electricity_use_kwh": 1000.0,
        }
    ]
    rows = build_gold_rows(
        buildings, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS, Decimal("25000"), covered_bbls=set()
    )
    assert rows == []


def test_build_gold_rows_produces_one_row_per_period_per_covered_building():
    buildings = [
        {
            "property_id": "12915497",
            "bbl": "1019820010",
            "property_name": "527 West 125th Street",
            "borough": "MANHATTAN",
            "primary_property_type": "Social/Meeting Hall",
            "gross_floor_area_ft": 33972.0,
            "year_ending": "12/31/2021",
            "total_ghg_emissions_tons": 72.4,
            "electricity_use_kwh": 81265.7,
            "natural_gas_use_kbtu": 978775.8,
        }
    ]
    rows = build_gold_rows(
        buildings, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS, Decimal("25000"),
        covered_bbls={"1019820010"},
    )
    assert len(rows) == 4
    assert {r["property_id"] for r in rows} == {"12915497"}
    assert {(r["period_start"], r["period_end"]) for r in rows} == set(PERIODS)
    assert all(r["reported_emissions_tco2e"] == 72.4 for r in rows)


def test_build_gold_rows_passes_through_raw_fuel_usage_unconverted():
    # Fuel usage for the UI's pie chart is a direct passthrough from
    # Silver — no coefficient math applied, matches the CSV's own values.
    buildings = [
        {
            "property_id": "12915497",
            "bbl": "1019820010",
            "primary_property_type": "Social/Meeting Hall",
            "gross_floor_area_ft": 33972.0,
            "year_ending": "12/31/2021",
            "electricity_use_kwh": 81265.7,
            "natural_gas_use_kbtu": 978775.8,
            "propane_use_kbtu": None,
        }
    ]
    rows = build_gold_rows(
        buildings, FUEL_COEFFICIENTS, EMISSIONS_CAPS, PENALTY_RATE, PERIODS, Decimal("25000"),
        covered_bbls={"1019820010"},
    )
    assert all(r["electricity_use_kwh"] == 81265.7 for r in rows)
    assert all(r["natural_gas_use_kbtu"] == 978775.8 for r in rows)
    assert all(r["propane_use_kbtu"] is None for r in rows)
    assert all(r["fuel_oil_5_6_use_kbtu"] is None for r in rows)  # not present on the building -> None, not an error
