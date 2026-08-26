import json
from unittest.mock import MagicMock, patch

from regulation_pipeline.chunking.docling_hybrid_chunker import Chunk
from regulation_pipeline.embedding.pgvector_embedder import (
    SEARCH_DOCUMENT_PREFIX,
    embed_and_store,
    embed_chunks,
    store_chunks,
)


def _chunk(chunk_id: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_key="doc-1",
        page_number=1,
        block_type="text",
        section="Some Section",
        section_path="Some Section",
        raw_text=text,
        full_text=text,
        chunk_meta={"k": "v"},
    )


@patch("regulation_pipeline.embedding.pgvector_embedder.SentenceTransformer")
def test_embed_chunks_prefixes_text_and_loads_model_fresh(mock_st_cls):
    chunks = [_chunk(0, "hello"), _chunk(1, "world")]
    mock_model = MagicMock()
    mock_model.encode.return_value.tolist.return_value = [[0.1, 0.2], [0.3, 0.4]]
    mock_st_cls.return_value = mock_model

    embeddings = embed_chunks("nomic-ai/nomic-embed-text-v1", chunks)

    mock_st_cls.assert_called_once_with("nomic-ai/nomic-embed-text-v1", trust_remote_code=True)
    mock_model.encode.assert_called_once_with(
        [SEARCH_DOCUMENT_PREFIX + "hello", SEARCH_DOCUMENT_PREFIX + "world"],
        normalize_embeddings=True,
    )
    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]


def test_store_chunks_inserts_document_chunk_and_embedding_rows():
    chunks = [_chunk(0, "hello")]
    embeddings = [[0.1, 0.2]]
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    store_chunks(conn, rag_id=7, chunks=chunks, embeddings=embeddings, model_name="nomic-ai/nomic-embed-text-v1")

    assert cursor.execute.call_count == 2

    chunk_sql, chunk_params = cursor.execute.call_args_list[0].args
    assert "insert into document_chunks" in chunk_sql
    assert chunk_params[0] == 7  # rag_id
    assert chunk_params[1] == 0  # chunk_id
    assert chunk_params[8] == "hello"  # full_text
    assert json.loads(chunk_params[9]) == {"k": "v"}

    embedding_sql, embedding_params = cursor.execute.call_args_list[1].args
    assert "insert into chunk_embeddings" in embedding_sql
    assert embedding_params == (7, 0, [0.1, 0.2], "nomic-ai/nomic-embed-text-v1")

    conn.commit.assert_called_once()


@patch("regulation_pipeline.embedding.pgvector_embedder.SentenceTransformer")
def test_embed_and_store_wires_embed_and_store_together(mock_st_cls):
    chunks = [_chunk(0, "hello")]
    mock_model = MagicMock()
    mock_model.encode.return_value.tolist.return_value = [[0.1, 0.2]]
    mock_st_cls.return_value = mock_model
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    settings = MagicMock(embed_model_hf_id="nomic-ai/nomic-embed-text-v1")

    embed_and_store(conn, settings, rag_id=3, chunks=chunks)

    mock_st_cls.assert_called_once()
    assert cursor.execute.call_count == 2
    conn.commit.assert_called_once()
