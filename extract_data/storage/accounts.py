"""
Taking one filing from its PDF url to the remote storage and the database.

For each filing the database query gives a filing id (the id of its `filing_history` row) and
the url of the accounts PDF.  The steps are:

1. download the PDF
2. OCR it (or read its text layer) into a plain text file
3. upload both files to the bucket (see ionos.py)
4. insert a row into `companies_house_accounts` (just the filing id), which is what records
   the filing as done

The row is inserted last, so a filing that failed part way has no row and is picked up again.

The steps of different filings overlap, so the GPU is not left waiting for the network: while one
filing is being OCRed the next few are already downloading and the previous ones are uploading.
The OCR and every database call stay on the calling thread (a database connection is not shared
between threads); only the downloads and uploads run on worker threads.
"""

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from mysql.connector import IntegrityError, errorcode

from extract_data.reading.ocr import DEFAULT_DPI, ocr_pdf, write_text_dump
from extract_data.storage import ionos

INSERT_RECORD = "INSERT INTO companies_house_accounts (filing_history_id) VALUES (%s)"
SITE = "https://find-and-update.company-information.service.gov.uk"  # for urls stored without a host
DOWNLOAD_TIMEOUT = 60  # seconds without an answer before giving up
DOWNLOAD_TRIES = 3  # a download that fails because of the network is tried this many times
RECONNECT_TRIES = 3  # tries to get a dropped database connection back before a filing fails
RETRY_WAIT = 5  # seconds before the second try, twice that before the third
DOWNLOAD_WORKERS = 3  # downloads running at once
PREFETCH = 4  # filings downloaded ahead of the one being OCRed
UPLOAD_WORKERS = 2  # uploads running at once


def local_paths(work_dir, filing_id):
    """Where a filing's PDF and text file are kept on this computer."""
    return work_dir / f"{filing_id}.pdf", work_dir / f"{filing_id}.txt"


def worth_retrying(error):
    """A network problem, a server error or "too many requests" may pass; "not found" and the like will not."""
    return not isinstance(error, HTTPError) or error.code >= 500 or error.code == 429


def fetch(url):
    """The bytes at `url`, trying again after a network problem."""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})  # Companies House refuses requests with no browser
    for attempt in range(1, DOWNLOAD_TRIES + 1):
        try:
            with urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                return response.read()
        except OSError as error:  # includes URLError, HTTPError and timeouts
            if attempt == DOWNLOAD_TRIES or not worth_retrying(error):
                raise
            time.sleep(RETRY_WAIT * attempt)


def download_pdf(url, path):
    """Save the file at `url` to `path`."""
    url = urljoin(SITE, url)
    data = fetch(url)
    if not data.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    Path(path).write_bytes(data)


def ocr_to_text(pdf_path, txt_path, cache_dir, dpi=DEFAULT_DPI):
    """Read the PDF (text layer or OCR) and write its text, page by page, to `txt_path`."""
    write_text_dump(ocr_pdf(pdf_path, cache_dir, dpi=dpi), Path(txt_path))


def record_filing(connection, filing_history_id):
    """
    Insert the row that logs the filing as downloaded and saved.

    If the filing already has a row (another run recorded it first) the database refuses the
    second one, since filing_history_id is unique (see SQL/2026_10_28__10_00.sql).  That is fine:
    the filing is recorded either way.

    A run can last hours and the server closes a connection that has been idle too long, so the
    connection is checked first and opened again if it was dropped.
    """
    connection.ping(reconnect=True, attempts=RECONNECT_TRIES, delay=RETRY_WAIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute(INSERT_RECORD, (filing_history_id,))
    except IntegrityError as error:
        if error.errno != errorcode.ER_DUP_ENTRY:
            raise
        connection.rollback()
    else:
        connection.commit()


def upload_filing(client, filing_id, pdf_path, txt_path):
    """Upload a filing's PDF and text file to the bucket."""
    pdf_key, txt_key = ionos.object_keys(filing_id)  # the keys follow from the id, so the row needs no path
    ionos.upload_file(client, pdf_path, pdf_key, "application/pdf")
    ionos.upload_file(client, txt_path, txt_key, "text/plain; charset=utf-8")


def record_uploaded(uploading, connection, wait):
    """
    Record the filings whose upload has finished, oldest first (all of them, waiting if need be, when
    `wait` is true).  Yields (filing id, error or None).
    """
    while uploading and (wait or uploading[0][1].done()):
        filing_id, upload = uploading.popleft()
        try:
            upload.result()
            record_filing(connection, filing_id)
        except Exception as error:  # one bad filing must not stop the rest
            yield filing_id, error
        else:
            yield filing_id, None


def save_filings(filings, work_dir, client, connection, dpi=DEFAULT_DPI, dry_run=False):
    """
    Download, OCR, upload and record each (filing id, url) of `filings`.

    Yields (filing id, error or None) as each filing finishes; a failure does not stop the others,
    and the filing gets no database row.  With `dry_run` only the download and OCR are done.
    `work_dir` holds the local copies and the OCR cache.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    waiting = iter(filings)
    downloading, uploading = deque(), deque()  # (filing id, future), oldest first

    with ThreadPoolExecutor(DOWNLOAD_WORKERS) as downloads, ThreadPoolExecutor(UPLOAD_WORKERS) as uploads:
        def start_downloads():
            while len(downloading) < PREFETCH:
                item = next(waiting, None)
                if item is None:
                    return
                filing_id, url = item
                pdf_path = local_paths(work_dir, filing_id)[0]
                downloading.append((filing_id, downloads.submit(download_pdf, url, pdf_path)))

        start_downloads()
        while downloading:
            filing_id, download = downloading.popleft()
            start_downloads()  # keep the next downloads going during the OCR
            pdf_path, txt_path = local_paths(work_dir, filing_id)
            try:
                download.result()
                ocr_to_text(pdf_path, txt_path, work_dir / "output", dpi)
            except Exception as error:
                yield filing_id, error
            else:
                if dry_run:
                    yield filing_id, None
                else:
                    upload = uploads.submit(upload_filing, client, filing_id, pdf_path, txt_path)
                    uploading.append((filing_id, upload))
            yield from record_uploaded(uploading, connection, wait=False)
        yield from record_uploaded(uploading, connection, wait=True)
