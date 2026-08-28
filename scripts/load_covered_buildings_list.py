"""One-time load of NYC's official LL97 Covered Buildings List PDF into a
Postgres table. Not a pipeline — no idempotency/versioning machinery, no
Docling/RAG. Run once (or re-run to fully replace the table if DOF
publishes an updated list):

    python scripts/load_covered_buildings_list.py

Requires `pdftotext` (poppler-utils, `brew install poppler`) on PATH.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import psycopg

from disclosure_pipeline.config import Settings

PDF_PATH = Path("data/disclosures/nyc_covered_buildings_list.pdf")

ROW_RE = re.compile(
    r"^(?P<bbl>\d{10})\s{2,}"
    r"(?P<water>Yes|No)\s{2,}"
    r"(?P<boro>\d)\s{2,}"
    r"(?P<block>\d+)\s{2,}"
    r"(?P<lot>\d+)\s{2,}"
    r"(?:(?P<easement>\S+)\s{2,})?"
    r"(?P<bclass>[A-Z0-9]{2})\s{2,}"
    r"(?P<taxclass>\d[A-Z]?)\s{2,}"
    r"(?P<bldgcount>\d+)\s{2,}"
    r"(?P<sqft>[\d,]+)\s+"
    r"(?:(?P<streetnum>\S+)\s+)?"
    r"(?P<streetname>.+?)\s+"
    r"(?P<zip>\d{1,5}(?:-\d{4})?)"
    r"(?:\s{2,}(?P<multiflag>\S+))?\s*$"
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS covered_buildings (
    bbl                       TEXT PRIMARY KEY,
    borough                   TEXT,
    block                     TEXT,
    lot                       TEXT,
    easement                  TEXT,
    building_class            TEXT,
    tax_class                 TEXT,
    building_count            INT,
    dof_square_footage        NUMERIC,
    street_number             TEXT,
    street_name               TEXT,
    zip_code                  TEXT,
    requires_water_data       BOOLEAN,
    multi_building_lot_flag   TEXT,
    source_file               TEXT NOT NULL,
    loaded_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

INSERT_ROW = """
INSERT INTO covered_buildings
    (bbl, borough, block, lot, easement, building_class, tax_class, building_count,
     dof_square_footage, street_number, street_name, zip_code, requires_water_data,
     multi_building_lot_flag, source_file)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (bbl) DO NOTHING
"""


def parse_rows(text: str) -> list[dict]:
    rows = []
    unmatched = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not re.match(r"^\d{10}\s", stripped):
            continue  # page headers/footers/notes — every real row starts with a 10-digit BBL
        match = ROW_RE.match(stripped)
        if match is None:
            unmatched += 1
            continue
        rows.append(match.groupdict())
    if unmatched:
        print(f"WARNING: {unmatched} BBL-prefixed lines did not match the row pattern and were skipped")
    return rows


def main() -> None:
    settings = Settings()
    text = subprocess.run(
        ["pdftotext", "-layout", str(PDF_PATH), "-"], capture_output=True, text=True, check=True
    ).stdout

    rows = parse_rows(text)
    print(f"parsed {len(rows)} rows")

    conn = psycopg.connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://"))
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE)
        cur.execute("TRUNCATE covered_buildings")
        for row in rows:
            cur.execute(
                INSERT_ROW,
                (
                    row["bbl"],
                    row["boro"],
                    row["block"],
                    row["lot"],
                    row["easement"],
                    row["bclass"],
                    row["taxclass"],
                    int(row["bldgcount"]),
                    row["sqft"].replace(",", ""),
                    row["streetnum"],
                    row["streetname"],
                    row["zip"],
                    row["water"] == "Yes",
                    row["multiflag"],
                    PDF_PATH.name,
                ),
            )
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM covered_buildings")
        print(f"loaded {cur.fetchone()[0]} rows into covered_buildings")
    conn.close()


if __name__ == "__main__":
    main()
