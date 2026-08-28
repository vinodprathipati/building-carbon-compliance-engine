"""Run the full regulation_pipeline (parse -> embed -> extract) for both
NYC source PDFs. FuelCoefficient draws from both documents (RCNY's
combustion-fuel table + Admin Code's utility-coefficient prose), so both
need to run for extraction to be complete.

    python scripts/run_regulation_pipeline.py [--force-regen]

--force-regen re-parses/re-embeds even if an unchanged version is already
active (normally both steps are skipped when the PDF hash hasn't changed).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg
from sentence_transformers import SentenceTransformer

from regulation_pipeline.config import Settings
from regulation_pipeline.extraction.llm_provider import AnthropicProvider
from regulation_pipeline.pipeline import run_pipeline

DOCUMENTS = [
    # (pdf_path, document_key, doc_type)
    (Path("data/raw_pdfs/1_RCNY_103-14.pdf"), "nyc_rcny_103-14", "regulation"),
    (Path("data/raw_pdfs/NYC_AdminCode_Chapter3.pdf"), "nyc_admincode_chapter3", "statute"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-regen", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    conn = psycopg.connect(settings.database_url.replace("postgresql+psycopg://", "postgresql://"))
    embed_model = SentenceTransformer(settings.embed_model_hf_id, trust_remote_code=True)
    llm = AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    for pdf_path, document_key, doc_type in DOCUMENTS:
        print(f"\n=== {document_key} ({pdf_path.name}) ===")
        result = run_pipeline(
            conn, settings, embed_model, llm, pdf_path, document_key, doc_type,
            force_regen=args.force_regen,
        )
        print(result)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
