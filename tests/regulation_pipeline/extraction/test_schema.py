import pytest

from regulation_pipeline.extraction.schema import ConceptSchema, FieldSpec, label_field, load_schema


def test_load_schema_loads_all_four_concepts():
    concepts = load_schema()

    assert set(concepts) == {
        "EmissionsFactor",
        "FuelCoefficient",
        "PenaltyRule",
        "CoveredBuildingRule",
    }


def test_emissions_factor_concept_shape():
    concepts = load_schema()
    concept = concepts["EmissionsFactor"]

    assert concept.extraction_method == "table"
    assert concept.natural_key == ["jurisdiction", "property_type", "period_start", "period_end"]
    field_ids = {f.id for f in concept.fields}
    assert field_ids == {"jurisdiction", "property_type", "period_start", "period_end", "value", "unit"}


def test_penalty_rule_has_enum_field():
    concepts = load_schema()
    concept = concepts["PenaltyRule"]

    rule_type = next(f for f in concept.fields if f.id == "rule_type")
    assert rule_type.data_type == "enum"
    assert rule_type.allowed_values == ["excess_emissions", "late_filing", "false_reporting"]


def test_label_field_identifies_the_concept_specific_field():
    concepts = load_schema()

    assert label_field(concepts["EmissionsFactor"]).id == "property_type"
    assert label_field(concepts["FuelCoefficient"]).id == "fuel_type"


def test_label_field_raises_when_no_non_standard_field_exists():
    concept = ConceptSchema(
        name="AllStandard",
        description="d",
        extraction_method="table",
        retrieval_hint="h",
        natural_key=["jurisdiction"],
        fields=[
            FieldSpec(id="jurisdiction", display_name="Jurisdiction", data_type="string", required=True, description="d"),
            FieldSpec(id="value", display_name="Value", data_type="number", required=True, description="d"),
        ],
    )

    with pytest.raises(ValueError, match="no label field"):
        label_field(concept)
