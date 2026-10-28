"""
Save the accounts PDFs listed in the database: download, OCR to text, upload to the IONOS
bucket and log each one in `companies_house_accounts`.

    python upload_filings.py --limit 3        try it on three filings first
    python upload_filings.py                  everything not saved yet
    python upload_filings.py --dry-run --limit 3   download and OCR only, no upload or database writes

Needs the environment variables RPP2_CONNSTR (database), IONOS_BUCKET_ACCESS_KEY and
IONOS_BUCKET_SECRET_KEY (bucket).  A filing that fails is reported and skipped; because its
database row is only written at the end, the next run tries it again.
"""

import argparse
import sys
from pathlib import Path

from extract_data.reading import gpu
from extract_data.reading.ocr import DEFAULT_DPI
from extract_data.storage import database, ionos
from extract_data.storage.accounts import download_pdf, ocr_to_text, process_filing


def build_parser():
    parser = argparse.ArgumentParser(description="Download, OCR and upload Companies House accounts PDFs.")
    parser.add_argument("--limit", type=int, default=1000000, help="most filings to do this run")
    parser.add_argument("--work-dir", default="downloads", help="folder for the local PDFs, text and OCR cache")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="resolution used to OCR scanned pages")
    parser.add_argument("--dry-run", action="store_true",
                        help="download and OCR only: no bucket keys needed, nothing uploaded, no database rows")
    parser.add_argument("--cpu", action="store_true", help="OCR on the CPU even if a GPU is available")
    return parser


def dry_run(filing_id, url, work_dir, dpi):
    """The local half of a filing only: download the PDF and write its text file."""
    folder = Path(work_dir)
    folder.mkdir(parents=True, exist_ok=True)
    pdf_path = folder / f"{filing_id}.pdf"
    download_pdf(url, pdf_path)
    ocr_to_text(pdf_path, folder / f"{filing_id}.txt", folder / "output", dpi)


def main(argv=None):
    args = build_parser().parse_args(argv)
    gpu.enabled = not args.cpu
    client = None if args.dry_run else ionos.make_client()  # fail early if the bucket keys are missing
    connection = database.connect()
    failed = []
    try:
        filings = database.pending_filings(connection, args.limit)
        print(f"{len(filings)} filing(s) to save")
        for filing_id, url in filings:
            try:
                if args.dry_run:
                    dry_run(filing_id, url, args.work_dir, args.dpi)
                else:
                    process_filing(filing_id, url, args.work_dir, client, connection, args.dpi)
                print(f"{'checked' if args.dry_run else 'saved'} filing {filing_id}")
            except Exception as error:  # one bad filing must not stop the rest
                failed.append(filing_id)
                print(f"FAILED filing {filing_id}: {error}")
    finally:
        connection.close()
    if failed:
        sys.exit(f"{len(failed)} filing(s) failed: {failed}")


if __name__ == "__main__":
    main()
