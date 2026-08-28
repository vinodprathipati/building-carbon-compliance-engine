from unittest.mock import MagicMock, patch

from regulation_pipeline.extraction.extractor import (
    extract_concept,
    extract_prose_concept,
    extract_table_concept,
    infer_document_jurisdiction,
)
from regulation_pipeline.extraction.llm_provider import LLMResponse
from regulation_pipeline.extraction.retriever import CandidateChunk
from regulation_pipeline.extraction.schema import ConceptSchema, FieldSpec


def _emissions_factor_concept() -> ConceptSchema:
    return ConceptSchema(
        name="EmissionsFactor",
        description="desc",
        extraction_method="table",
        retrieval_hint="hint",
        natural_key=["jurisdiction", "property_type", "period_start", "period_end"],
        fields=[
            FieldSpec(id="jurisdiction", display_name="Jurisdiction", data_type="string", required=True, description="d"),
            FieldSpec(id="property_type", display_name="Property Type", data_type="string", required=True, description="d"),
            FieldSpec(id="period_start", display_name="Period Start", data_type="integer", required=True, description="d"),
            FieldSpec(id="period_end", display_name="Period End", data_type="integer", required=True, description="d"),
            FieldSpec(id="value", display_name="Value", data_type="number", required=True, description="d"),
            FieldSpec(id="unit", display_name="Unit", data_type="string", required=True, description="d"),
        ],
    )


def _penalty_rule_concept() -> ConceptSchema:
    return ConceptSchema(
        name="PenaltyRule",
        description="desc",
        extraction_method="prose",
        retrieval_hint="hint",
        natural_key=["jurisdiction", "rule_type"],
        fields=[
            FieldSpec(id="jurisdiction", display_name="Jurisdiction", data_type="string", required=True, description="d"),
            FieldSpec(
                id="rule_type",
                display_name="Rule Type",
                data_type="enum",
                required=True,
                description="d",
                allowed_values=["excess_emissions"],
            ),
            FieldSpec(id="rate", display_name="Rate", data_type="number", required=True, description="d"),
            FieldSpec(id="rate_unit", display_name="Rate Unit", data_type="string", required=True, description="d"),
        ],
    )


def _table_candidate(chunk_id: int) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=chunk_id,
        page_number=42,
        block_type="table",
        section="sec",
        raw_text="raw",
        full_text="full",
        chunk_meta={"table_ref": "#/tables/8", "column_headers": ["ESPM Property Type", "2024-2029 Factor"]},
        similarity=0.9,
    )


def _prose_candidate(chunk_id: int) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=chunk_id,
        page_number=37,
        block_type="text",
        section="Penalties",
        raw_text="An owner ... $268 per ton.",
        full_text="full",
        chunk_meta={},
        similarity=0.9,
    )


@patch("regulation_pipeline.extraction.extractor.search_chunks")
@patch("regulation_pipeline.extraction.extractor.embed_query")
def test_extract_table_concept_reads_document_tables_deterministically(mock_embed, mock_search):
    mock_embed.return_value = [0.1, 0.2]
    mock_search.return_value = [_table_candidate(47)]

    llm = MagicMock()
    llm.messages_create.return_value = LLMResponse(
        text=(
            '{"is_match": true, "jurisdiction": "New York City", '
            '"label_column": "ESPM Property Type", "value_column": "2024-2029 Factor", '
            '"period_start": 2024, "period_end": 2029, "unit": "tCO2e/sf"}'
        ),
        input_tokens=10,
        output_tokens=10,
    )

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = ([{"ESPM Property Type": "Office", "2024-2029 Factor": "0.00758"}],)

    records = extract_table_concept(conn, llm, MagicMock(), _emissions_factor_concept(), rag_id=6)

    assert records == [
        {
            "property_type": "Office",
            "value": "0.00758",
            "jurisdiction": "New York City",
            "period_start": 2024,
            "period_end": 2029,
            "unit": "tCO2e/sf",
            "chunk_id": 47,
        }
    ]
    llm.messages_create.assert_called_once()  # one call for the one candidate
    cursor.execute.assert_called_once_with(
        "select rows from document_tables where rag_id = %s and chunk_id = %s", (6, 47)
    )


@patch("regulation_pipeline.extraction.extractor.search_chunks")
@patch("regulation_pipeline.extraction.extractor.embed_query")
def test_extract_table_concept_classifies_each_candidate_independently(mock_embed, mock_search):
    mock_embed.return_value = [0.1, 0.2]
    mock_search.return_value = [_table_candidate(47), _table_candidate(48), _table_candidate(49)]

    llm = MagicMock()
    llm.messages_create.side_effect = [
        LLMResponse(
            text=(
                '{"is_match": true, "jurisdiction": "New York City", "label_column": "ESPM Property Type", '
                '"value_column": "2024-2029 Factor", "period_start": 2024, "period_end": 2029, "unit": "tCO2e/sf"}'
            ),
            input_tokens=10,
            output_tokens=10,
        ),
        LLMResponse(text='{"is_match": false}', input_tokens=10, output_tokens=5),
        LLMResponse(
            text=(
                '{"is_match": true, "jurisdiction": "New York City", "label_column": "ESPM Property Type", '
                '"value_column": "2024-2029 Factor", "period_start": 2024, "period_end": 2029, "unit": "tCO2e/sf"}'
            ),
            input_tokens=10,
            output_tokens=10,
        ),
    ]

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = ([{"ESPM Property Type": "Office", "2024-2029 Factor": "0.00758"}],)

    records = extract_table_concept(conn, llm, MagicMock(), _emissions_factor_concept(), rag_id=6)

    assert llm.messages_create.call_count == 3  # one call per candidate, no batching
    assert {r["chunk_id"] for r in records} == {47, 49}  # candidate 48 (is_match=false) excluded


@patch("regulation_pipeline.extraction.extractor.search_chunks")
@patch("regulation_pipeline.extraction.extractor.embed_query")
def test_extract_table_concept_returns_empty_when_no_table_candidates(mock_embed, mock_search):
    mock_embed.return_value = [0.1, 0.2]
    mock_search.return_value = [_prose_candidate(9)]  # block_type != 'table'

    llm = MagicMock()
    records = extract_table_concept(MagicMock(), llm, MagicMock(), _emissions_factor_concept(), rag_id=6)

    assert records == []
    llm.messages_create.assert_not_called()


@patch("regulation_pipeline.extraction.extractor.search_chunks")
@patch("regulation_pipeline.extraction.extractor.embed_query")
def test_extract_prose_concept_returns_llm_records_directly(mock_embed, mock_search):
    mock_embed.return_value = [0.1, 0.2]
    mock_search.return_value = [_prose_candidate(9)]

    llm = MagicMock()
    llm.messages_create.return_value = LLMResponse(
        text=(
            '{"records": [{"jurisdiction": "New York City", "rule_type": "excess_emissions", '
            '"rate": 268, "rate_unit": "$/tCO2e", "chunk_id": 9, "extracted_quote": "quote"}]}'
        ),
        input_tokens=10,
        output_tokens=10,
    )

    records = extract_prose_concept(MagicMock(), llm, MagicMock(), _penalty_rule_concept(), rag_id=6)

    assert records == [
        {
            "jurisdiction": "New York City",
            "rule_type": "excess_emissions",
            "rate": 268,
            "rate_unit": "$/tCO2e",
            "chunk_id": 9,
            "extracted_quote": "quote",
        }
    ]


@patch("regulation_pipeline.extraction.extractor.extract_prose_concept")
@patch("regulation_pipeline.extraction.extractor.extract_table_concept")
def test_extract_concept_dispatches_by_extraction_method(mock_table, mock_prose):
    mock_table.return_value = ["table-result"]
    mock_prose.return_value = ["prose-result"]
    conn = llm = embed_model = MagicMock()

    assert extract_concept(conn, llm, embed_model, _emissions_factor_concept(), rag_id=6) == ["table-result"]
    mock_table.assert_called_once()
    mock_prose.assert_not_called()

    assert extract_concept(conn, llm, embed_model, _penalty_rule_concept(), rag_id=6) == ["prose-result"]
    mock_prose.assert_called_once()


def test_infer_document_jurisdiction_uses_early_chunks_only():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [("Title page of the NYC Admin Code...",), ("Chapter 3, Article 320...",)]

    llm = MagicMock()
    llm.messages_create.return_value = LLMResponse(
        text='{"jurisdiction": "New York City"}', input_tokens=10, output_tokens=10
    )

    result = infer_document_jurisdiction(conn, llm, rag_id=9)

    assert result == "New York City"
    cursor.execute.assert_called_once_with(
        "select full_text\n"
        "from document_chunks\n"
        "where rag_id = %s\n"
        "order by page_number nulls last, chunk_id\n"
        "limit %s",
        (9, 3),
    )
    llm.messages_create.assert_called_once()  # one call for the whole document, not per candidate


def test_infer_document_jurisdiction_returns_none_when_not_stated():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [("Some generic regulatory text with no place name.",)]

    llm = MagicMock()
    llm.messages_create.return_value = LLMResponse(text='{"jurisdiction": null}', input_tokens=10, output_tokens=10)

    assert infer_document_jurisdiction(conn, llm, rag_id=9) is None


def test_infer_document_jurisdiction_returns_none_when_no_chunks_exist():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = []

    llm = MagicMock()

    assert infer_document_jurisdiction(conn, llm, rag_id=9) is None
    llm.messages_create.assert_not_called()
