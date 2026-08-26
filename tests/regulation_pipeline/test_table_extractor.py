from docling_core.types.doc import DoclingDocument, DocItemLabel
from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.document import ProvenanceItem, TableCell, TableData

from regulation_pipeline.chunking.table_extractor import extract_table_descriptors, to_chunk


def _prov(page_no: int = 1) -> ProvenanceItem:
    return ProvenanceItem(
        page_no=page_no, bbox=BoundingBox(l=0, t=100, r=100, b=0), charspan=(0, 10)
    )


def _cell(text: str, row: int, col: int, *, header: bool = False) -> TableCell:
    return TableCell(
        bbox=BoundingBox(l=0, t=0, r=1, b=1),
        row_span=1,
        col_span=1,
        start_row_offset_idx=row,
        end_row_offset_idx=row + 1,
        start_col_offset_idx=col,
        end_col_offset_idx=col + 1,
        text=text,
        column_header=header,
        row_header=False,
        row_section=False,
    )


def _build_document() -> DoclingDocument:
    cells = [
        _cell("Property Type", 0, 0, header=True),
        _cell("2024-2029 Factor", 0, 1, header=True),
        _cell("Office", 1, 0),
        _cell("0.00758", 1, 1),
        _cell("Retail", 2, 0),
        _cell("0.00675", 2, 1),
    ]
    data = TableData(table_cells=cells, num_rows=3, num_cols=2)

    doc = DoclingDocument(name="test-doc")
    heading = doc.add_heading(text="Emissions factors", level=1, prov=_prov(42))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="For calendar years 2024-2029, the following factors apply:",
        prov=_prov(42),
        parent=heading,
    )
    doc.add_table(data=data, prov=_prov(42))
    return doc


def test_extract_table_descriptors_builds_descriptor_and_rows():
    doc = _build_document()

    descriptors = extract_table_descriptors(doc, document_key="test-doc", start_chunk_id=5)

    assert len(descriptors) == 1
    d = descriptors[0]
    assert d.chunk_id == 5
    assert d.document_key == "test-doc"
    assert d.page_number == 42
    assert d.section == "Emissions factors"
    assert d.table_ref == "#/tables/0"
    assert d.column_headers == ["Property Type", "2024-2029 Factor"]
    assert d.rows == [
        {"Property Type": "Office", "2024-2029 Factor": "0.00758"},
        {"Property Type": "Retail", "2024-2029 Factor": "0.00675"},
    ]
    assert "Emissions factors" in d.descriptor_text
    assert "For calendar years 2024-2029" in d.descriptor_text
    assert "Property Type | 2024-2029 Factor" in d.descriptor_text
    # row data must not leak into the descriptor text
    assert "0.00758" not in d.descriptor_text


def test_extract_table_descriptors_continuation_table_inherits_previous_headers():
    first_cells = [
        _cell("Property Type", 0, 0, header=True),
        _cell("2024-2029 Factor", 0, 1, header=True),
        _cell("Office", 1, 0),
        _cell("0.00758", 1, 1),
    ]
    first_data = TableData(table_cells=first_cells, num_rows=2, num_cols=2)

    # No column_header=True cells at all — mirrors a page-boundary
    # continuation table Docling didn't attach a header row to.
    second_cells = [
        _cell("Retail", 0, 0),
        _cell("0.00675", 0, 1),
    ]
    second_data = TableData(table_cells=second_cells, num_rows=1, num_cols=2)

    doc = DoclingDocument(name="continuation-doc")
    heading = doc.add_heading(text="Emissions factors", level=1, prov=_prov(42))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="For calendar years 2024-2029, the following factors apply:",
        prov=_prov(42),
        parent=heading,
    )
    doc.add_table(data=first_data, prov=_prov(42))
    doc.add_table(data=second_data, prov=_prov(43))

    descriptors = extract_table_descriptors(doc, document_key="continuation-doc")

    assert len(descriptors) == 2
    first, second = descriptors
    assert first.column_headers == ["Property Type", "2024-2029 Factor"]
    assert second.column_headers == ["Property Type", "2024-2029 Factor"]
    assert second.rows == [{"Property Type": "Retail", "2024-2029 Factor": "0.00675"}]
    # inherited context too, not just headers
    assert second.section == first.section
    assert "Property Type | 2024-2029 Factor" in second.descriptor_text


def test_extract_table_descriptors_continuation_overrides_misdetected_header_row():
    # Mirrors the real bug found on 1_RCNY_103-14.pdf table #9: a
    # continuation table where Docling wrongly flagged a mid-list data row
    # (not the first row) as column_header=True. Must not (a) keep that
    # wrong header label, or (b) silently drop that row from `rows`.
    first_cells = [
        _cell("Property Type", 0, 0, header=True),
        _cell("2024-2029 Factor", 0, 1, header=True),
        _cell("Office", 1, 0),
        _cell("0.00758", 1, 1),
    ]
    first_data = TableData(table_cells=first_cells, num_rows=2, num_cols=2)

    second_cells = [
        _cell("Retail", 0, 0),
        _cell("0.00675", 0, 1),
        # wrongly flagged as a header row by Docling's layout model
        _cell("Museum", 1, 0, header=True),
        _cell("0.01181", 1, 1, header=True),
        _cell("Warehouse", 2, 0),
        _cell("0.00426", 2, 1),
    ]
    second_data = TableData(table_cells=second_cells, num_rows=3, num_cols=2)

    doc = DoclingDocument(name="misdetected-header-doc")
    heading = doc.add_heading(text="Emissions factors", level=1, prov=_prov(42))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="For calendar years 2024-2029, the following factors apply:",
        prov=_prov(42),
        parent=heading,
    )
    doc.add_table(data=first_data, prov=_prov(42))
    doc.add_table(data=second_data, prov=_prov(43))

    descriptors = extract_table_descriptors(doc, document_key="misdetected-header-doc")

    assert len(descriptors) == 2
    second = descriptors[1]
    assert second.column_headers == ["Property Type", "2024-2029 Factor"]
    assert second.rows == [
        {"Property Type": "Retail", "2024-2029 Factor": "0.00675"},
        {"Property Type": "Museum", "2024-2029 Factor": "0.01181"},
        {"Property Type": "Warehouse", "2024-2029 Factor": "0.00426"},
    ]


def test_extract_table_descriptors_different_table_with_own_header_is_not_overridden():
    # Mirrors the real page-44 table: same column count, immediately
    # follows another table, no section header in between — but it's a
    # genuinely different table (a new compliance period) with its own real
    # header, which Docling correctly detected. Must NOT be overridden.
    first_cells = [
        _cell("Property Type", 0, 0, header=True),
        _cell("2024-2029 Factor", 0, 1, header=True),
        _cell("Office", 1, 0),
        _cell("0.00758", 1, 1),
    ]
    first_data = TableData(table_cells=first_cells, num_rows=2, num_cols=2)

    second_cells = [
        _cell("Property Type", 0, 0, header=True),
        _cell("2030-2034 Factor", 0, 1, header=True),
        _cell("Office", 1, 0),
        _cell("0.00269", 1, 1),
    ]
    second_data = TableData(table_cells=second_cells, num_rows=2, num_cols=2)

    doc = DoclingDocument(name="different-table-doc")
    heading = doc.add_heading(text="Emissions factors", level=1, prov=_prov(42))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="Factors by period:",
        prov=_prov(42),
        parent=heading,
    )
    doc.add_table(data=first_data, prov=_prov(42))
    doc.add_table(data=second_data, prov=_prov(44))

    descriptors = extract_table_descriptors(doc, document_key="different-table-doc")

    assert len(descriptors) == 2
    second = descriptors[1]
    assert second.column_headers == ["Property Type", "2030-2034 Factor"]
    assert second.rows == [{"Property Type": "Office", "2030-2034 Factor": "0.00269"}]


def test_extract_table_descriptors_no_tables_returns_empty():
    doc = DoclingDocument(name="empty-doc")
    doc.add_heading(text="No tables here", level=1, prov=_prov())

    assert extract_table_descriptors(doc, document_key="empty-doc") == []


def test_to_chunk_maps_descriptor_fields():
    doc = _build_document()
    descriptor = extract_table_descriptors(doc, document_key="test-doc")[0]

    chunk = to_chunk(descriptor)

    assert chunk.chunk_id == descriptor.chunk_id
    assert chunk.block_type == "table"
    assert chunk.section == "Emissions factors"
    assert chunk.raw_text == descriptor.descriptor_text
    assert chunk.full_text == descriptor.descriptor_text
    assert chunk.chunk_meta == {
        "table_ref": "#/tables/0",
        "column_headers": ["Property Type", "2024-2029 Factor"],
    }
