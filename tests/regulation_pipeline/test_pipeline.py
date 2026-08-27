import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from regulation_pipeline.pipeline import _get_or_create_rag_document, _run_step, run_pipeline


def _conn_and_cursor():
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


# ── _run_step ──────────────────────────────────────────────────────────────


def test_run_step_records_success_with_meta():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.return_value = (10,)

    result = _run_step(conn, run_id=1, step_name="parsing", fn=lambda: {"chunk_count": 39})

    assert result == {"chunk_count": 39}
    insert_sql, insert_params = cursor.execute.call_args_list[0].args
    assert "insert into pipeline_steps" in insert_sql
    assert insert_params == (1, "parsing")
    update_sql, update_params = cursor.execute.call_args_list[1].args
    assert "status = 'success'" in update_sql
    assert json.loads(update_params[0]) == {"chunk_count": 39}
    assert update_params[2] == 10  # step_id
    assert conn.commit.call_count == 2


def test_run_step_records_failure_and_reraises():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.return_value = (10,)

    def failing():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        _run_step(conn, run_id=1, step_name="extraction", fn=failing)

    update_sql, update_params = cursor.execute.call_args_list[1].args
    assert "status = 'failed'" in update_sql
    assert update_params[0] == "boom"


# ── _get_or_create_rag_document ──────────────────────────────────────────────


def test_get_or_create_rag_document_creates_new_when_none_exists():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.side_effect = [None, (5,)]  # no existing row, then new rag_id

    rag_id, skipped = _get_or_create_rag_document(conn, "doc-key", "hash-a", "model", force_regen=False)

    assert (rag_id, skipped) == (5, False)
    insert_sql, insert_params = cursor.execute.call_args_list[-1].args
    assert "insert into rag_documents" in insert_sql
    assert insert_params == ("doc-key", "hash-a", "model", 1)


def test_get_or_create_rag_document_skips_when_hash_unchanged():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.return_value = (5, "hash-a", 1)  # existing active row, same hash

    rag_id, skipped = _get_or_create_rag_document(conn, "doc-key", "hash-a", "model", force_regen=False)

    assert (rag_id, skipped) == (5, True)
    assert cursor.execute.call_count == 1  # only the lookup — no insert/update


def test_get_or_create_rag_document_creates_new_version_when_hash_changed():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.side_effect = [(5, "hash-a", 1), (6,)]  # existing row, then new rag_id

    rag_id, skipped = _get_or_create_rag_document(conn, "doc-key", "hash-b", "model", force_regen=False)

    assert (rag_id, skipped) == (6, False)
    deactivate_sql, deactivate_params = cursor.execute.call_args_list[1].args
    assert "update rag_documents set active_flag = false" in deactivate_sql
    assert deactivate_params == (5,)
    insert_sql, insert_params = cursor.execute.call_args_list[2].args
    assert insert_params == ("doc-key", "hash-b", "model", 2)  # version incremented


def test_get_or_create_rag_document_force_regen_ignores_matching_hash():
    conn, cursor = _conn_and_cursor()
    cursor.fetchone.side_effect = [(5, "hash-a", 1), (6,)]

    rag_id, skipped = _get_or_create_rag_document(conn, "doc-key", "hash-a", "model", force_regen=True)

    assert (rag_id, skipped) == (6, False)


# ── run_pipeline ──────────────────────────────────────────────────────────


@patch("regulation_pipeline.pipeline._run_extraction")
@patch("regulation_pipeline.pipeline._embed_document")
@patch("regulation_pipeline.pipeline._parse_document")
def test_run_pipeline_happy_path_new_document(mock_parse, mock_embed, mock_extraction, tmp_path):
    mock_parse.return_value = (["chunk"] * 39, ["table"] * 26, {"general_chunk_count": 39, "table_count": 26})
    mock_embed.return_value = {"embedded_chunk_count": 65}
    mock_extraction.return_value = {"EmissionsFactor": 238}

    conn, cursor = _conn_and_cursor()
    cursor.fetchone.side_effect = [
        (1,),  # pipeline_runs id
        None,  # no existing rag_documents row
        (10,),  # new rag_id
        (100,),  # pipeline_steps id (parsing)
        (101,),  # pipeline_steps id (embedding)
        (102,),  # pipeline_steps id (extraction)
    ]

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake content")

    result = run_pipeline(
        conn, MagicMock(embed_model_hf_id="model"), MagicMock(), MagicMock(),
        pdf_path=pdf_path, document_key="doc-key", doc_type="regulation",
    )

    assert result["rag_id"] == 10
    assert result["skipped_ingest"] is False
    assert result["parsing"] == {"general_chunk_count": 39, "table_count": 26}
    assert result["embedding"] == {"embedded_chunk_count": 65}
    assert result["extraction_counts"] == {"EmissionsFactor": 238}
    mock_parse.assert_called_once()
    mock_embed.assert_called_once()
    mock_extraction.assert_called_once()

    final_update_sql, final_update_params = cursor.execute.call_args_list[-1].args
    assert "update pipeline_runs" in final_update_sql
    assert final_update_params == ("success", None, 10, 1)


@patch("regulation_pipeline.pipeline._run_extraction")
@patch("regulation_pipeline.pipeline._embed_document")
@patch("regulation_pipeline.pipeline._parse_document")
def test_run_pipeline_skips_ingest_when_hash_unchanged(mock_parse, mock_embed, mock_extraction, tmp_path):
    mock_extraction.return_value = {"EmissionsFactor": 238}

    conn, cursor = _conn_and_cursor()
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"same content")
    import hashlib

    document_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

    cursor.fetchone.side_effect = [
        (1,),  # pipeline_runs id
        (10, document_hash, 1),  # existing active rag_documents row, unchanged hash
        (102,),  # pipeline_steps id (extraction) — only step run
    ]

    result = run_pipeline(
        conn, MagicMock(embed_model_hf_id="model"), MagicMock(), MagicMock(),
        pdf_path=pdf_path, document_key="doc-key", doc_type="regulation",
    )

    assert result["skipped_ingest"] is True
    assert result["parsing"] == {"skipped": True, "reason": "unchanged document_hash"}
    assert result["embedding"] == {"skipped": True, "reason": "unchanged document_hash"}
    mock_parse.assert_not_called()
    mock_embed.assert_not_called()
    mock_extraction.assert_called_once()


@patch("regulation_pipeline.pipeline._run_extraction")
@patch("regulation_pipeline.pipeline._embed_document")
@patch("regulation_pipeline.pipeline._parse_document")
def test_run_pipeline_marks_run_failed_on_step_error(mock_parse, mock_embed, mock_extraction, tmp_path):
    mock_parse.side_effect = RuntimeError("chunking exploded")

    conn, cursor = _conn_and_cursor()
    cursor.fetchone.side_effect = [
        (1,),  # pipeline_runs id
        None,  # no existing rag_documents row
        (10,),  # new rag_id
        (100,),  # pipeline_steps id (parsing)
    ]

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"content")

    with pytest.raises(RuntimeError, match="chunking exploded"):
        run_pipeline(
            conn, MagicMock(embed_model_hf_id="model"), MagicMock(), MagicMock(),
            pdf_path=pdf_path, document_key="doc-key", doc_type="regulation",
        )

    final_update_sql, final_update_params = cursor.execute.call_args_list[-1].args
    assert "update pipeline_runs" in final_update_sql
    assert final_update_params[0] == "failed"
    assert "chunking exploded" in final_update_params[1]
    assert final_update_params[2] is None  # rag_id not recorded on failure path taken here
    mock_embed.assert_not_called()  # parsing failed before embedding could run
