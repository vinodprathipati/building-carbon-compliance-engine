from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc import DoclingDocument
from docling_core.types.doc.document import TableItem, TextItem

from regulation_pipeline.chunking.docling_hybrid_chunker import Chunk


@dataclass
class TableDescriptor:
    chunk_id: int
    document_key: str
    page_number: int | None
    section: str | None
    table_ref: str
    caption: str
    column_headers: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)
    descriptor_text: str = ""


def _flagged_headers(table: TableItem) -> list[str]:
    headers = [""] * table.data.num_cols
    for row in table.data.grid:
        for cell in row:
            if cell.column_header and cell.start_col_offset_idx < len(headers):
                headers[cell.start_col_offset_idx] = cell.text.strip()
    return headers


def _is_numeric(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def _looks_like_real_header(headers: list[str]) -> bool:
    # A real header is a descriptive label. A data row Docling mistakenly
    # flagged as a header row (seen on real RCNY continuation tables) has at
    # least one cell that's just a bare number.
    return any(headers) and not any(_is_numeric(h) for h in headers if h)


def _first_row_texts(table: TableItem) -> list[str] | None:
    grid = table.data.grid
    if not grid or any(cell.row_section for cell in grid[0]):
        return None
    texts = [cell.text.strip() for cell in grid[0]]
    return texts if any(texts) else None


def _resolve_table(
    table: TableItem,
    previous_headers: list[str] | None,
    previous_num_cols: int | None,
    section_since_last_table: bool,
) -> tuple[list[str], list[dict[str, str]], bool]:
    """Resolve a table's column headers and data rows.

    Tries, in order: (1) Docling's flagged header row, if it looks like a
    real header rather than a data row it mistakenly flagged; (2) the grid's
    own first row, if it looks like a header despite not being flagged as
    one (seen on real RCNY tables where Docling missed the header row
    entirely); (3) inheriting headers from an immediately preceding,
    same-shaped table with no section boundary in between — a page-boundary
    continuation of it. Falls back to no headers if none of those apply.
    """
    flagged = _flagged_headers(table)
    grid = table.data.grid

    if _looks_like_real_header(flagged):
        headers = flagged
        skip_first_row = False
        is_continuation = False
    else:
        first_row = _first_row_texts(table)
        if first_row is not None and _looks_like_real_header(first_row):
            headers = first_row
            skip_first_row = True
            is_continuation = False
        elif (
            previous_headers is not None
            and not section_since_last_table
            and table.data.num_cols == previous_num_cols
        ):
            headers = previous_headers
            skip_first_row = False
            is_continuation = True
        else:
            headers = flagged
            skip_first_row = False
            is_continuation = False

    rows: list[dict[str, str]] = []
    for i, row in enumerate(grid):
        if any(cell.row_section for cell in row):
            continue
        if i == 0 and skip_first_row:
            continue
        if not is_continuation and any(cell.column_header for cell in row):
            continue
        cells = [cell.text.strip() for cell in row]
        if not any(cells):
            continue
        rows.append(
            {
                (headers[j] if j < len(headers) and headers[j] else f"col_{j}"): text
                for j, text in enumerate(cells)
            }
        )

    return headers, rows, is_continuation


def extract_table_descriptors(
    document: DoclingDocument, document_key: str, start_chunk_id: int = 0
) -> list[TableDescriptor]:
    descriptors: list[TableDescriptor] = []
    current_section: str | None = None
    last_text: str | None = None
    chunk_id = start_chunk_id
    previous_table_headers: list[str] | None = None
    previous_table_num_cols: int | None = None
    section_since_last_table = True

    for item, _level in document.iterate_items():
        if isinstance(item, TextItem):
            if str(item.label) == "section_header":
                current_section = item.text.strip()
                last_text = None
                section_since_last_table = True
            else:
                text = item.text.strip()
                if text:
                    last_text = text
            continue

        if not isinstance(item, TableItem):
            continue

        column_headers, rows, _is_continuation = _resolve_table(
            item, previous_table_headers, previous_table_num_cols, section_since_last_table
        )
        caption = item.caption_text(document)
        page_number = item.prov[0].page_no if item.prov else None
        header_line = " | ".join(h for h in column_headers if h)

        descriptor_text = "\n".join(
            part for part in [current_section, last_text, caption, header_line] if part
        )

        descriptors.append(
            TableDescriptor(
                chunk_id=chunk_id,
                document_key=document_key,
                page_number=page_number,
                section=current_section,
                table_ref=item.self_ref,
                caption=caption,
                column_headers=column_headers,
                rows=rows,
                descriptor_text=descriptor_text,
            )
        )
        chunk_id += 1
        previous_table_headers = column_headers
        previous_table_num_cols = item.data.num_cols
        section_since_last_table = False

    return descriptors


def extract_tables_from_pdf(
    pdf_path: Path, document_key: str, start_chunk_id: int = 0
) -> list[TableDescriptor]:
    document = DocumentConverter().convert(pdf_path).document
    return extract_table_descriptors(document, document_key, start_chunk_id)


def to_chunk(descriptor: TableDescriptor) -> Chunk:
    return Chunk(
        chunk_id=descriptor.chunk_id,
        document_key=descriptor.document_key,
        page_number=descriptor.page_number,
        block_type="table",
        section=descriptor.section,
        section_path=descriptor.section,
        raw_text=descriptor.descriptor_text,
        full_text=descriptor.descriptor_text,
        chunk_meta={"table_ref": descriptor.table_ref, "column_headers": descriptor.column_headers},
    )
