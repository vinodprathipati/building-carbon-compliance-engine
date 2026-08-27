from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_NAME_MARKER = re.compile(r"^-- name:\s*(\S+)\s*$", re.MULTILINE)


@lru_cache(maxsize=None)
def load_named_blocks(path: Path) -> dict[str, str]:
    """Parse a file of `-- name: block_name` marked sections into a dict.
    Shared by db/queries.sql (SQL) and extraction/prompt_templates.txt
    (LLM prompts) — same "one file, named blocks" shape either way."""
    text = path.read_text()
    markers = list(_NAME_MARKER.finditer(text))
    blocks: dict[str, str] = {}
    for i, marker in enumerate(markers):
        name = marker.group(1)
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        blocks[name] = text[start:end].strip()
    return blocks
