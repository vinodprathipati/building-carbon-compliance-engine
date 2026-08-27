from __future__ import annotations

from pathlib import Path

from regulation_pipeline.text_blocks import load_named_blocks

QUERIES_PATH = Path(__file__).resolve().parent / "queries.sql"


def sql(name: str) -> str:
    return load_named_blocks(QUERIES_PATH)[name]
