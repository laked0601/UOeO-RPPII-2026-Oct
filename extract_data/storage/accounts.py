"""
Taking one filing from its PDF url to the remote storage and the database.

For each filing the database query gives a filing id (the id of its `filing_history` row) and
the url of the accounts PDF.  The steps are:

1. download the PDF
2. OCR it (or read its text layer) into a plain text file
3. upload both files to the bucket (see ionos.py)
4. insert a row into `companies_house_accounts` (the filing id and the bucket key of the text file),
   which is what records the filing as done

The row is inserted last, so a filing that failed part way has no row and is picked up again.
"""

from extract_data.reading.ocr import DEFAULT_DPI, ocr_pdf, write_text_dump
from extract_data.storage import ionos
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

INSERT_RECORD = "INSERT INTO companies_house_accounts (filing_history_id, text_file_path) VALUES (%s, %s)"
SITE = "https://find-and-update.company-information.service.gov.uk"  # for urls stored without a host
DOWNLOAD_TIMEOUT = 60  # seconds without an answer before giving up


def download_pdf(url, path):
    """Save the file at `url` to `path`.  Companies House refuses requests that name no browser."""
    url = urljoin(SITE, url)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        data = response.read()
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    Path(path).write_bytes(data)


def ocr_to_text(pdf_path, txt_path, cache_dir, dpi=DEFAULT_DPI):
    """Read the PDF (text layer or OCR) and write its text, page by page, to `txt_path`."""
    write_text_dump(ocr_pdf(pdf_path, cache_dir, dpi=dpi), Path(txt_path))


def record_filing(connection, filing_history_id, text_key):
    """Insert the row that logs the filing as downloaded and saved; `text_key` is where its text is kept."""
    with connection.cursor() as cursor:
        cursor.execute(INSERT_RECORD, (filing_history_id, text_key))
    connection.commit()


def process_filing(filing_id, url, work_dir, client, connection, dpi=DEFAULT_DPI):
    """
    Download, OCR, upload and record one filing.  Raises on any failure, before the
    database row is written.  `work_dir` holds the local copies and the OCR cache.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path, txt_path = work_dir / f"{filing_id}.pdf", work_dir / f"{filing_id}.txt"

    download_pdf(url, pdf_path)
    ocr_to_text(pdf_path, txt_path, work_dir / "output", dpi)

    pdf_key, txt_key = ionos.object_keys(filing_id)
    ionos.upload_file(client, pdf_path, pdf_key, "application/pdf")
    ionos.upload_file(client, txt_path, txt_key, "text/plain; charset=utf-8")
    record_filing(connection, filing_id, txt_key)
