"""
Save the accounts PDFs listed in the database: download, OCR to text, upload to the IONOS
bucket and log each one in `companies_house_accounts`.

    python upload_filings.py --limit 3        try it on three filings first
    python upload_filings.py                  everything not saved yet
    python upload_filings.py --since 2020 --newest-first   2020 onwards, newest first
    python upload_filings.py --dry-run --limit 3   download and OCR only, no upload or database writes

Each run also writes a log of everything it printed to the logs folder, in a file named by the
time the run started and how many filings it handled, for example
logs/2026-10-28_14-05-33_50-filings.txt.

Needs the environment variables RPP2_CONNSTR (database), IONOS_BUCKET_ACCESS_KEY and
IONOS_BUCKET_SECRET_KEY (bucket).  A filing that fails is reported and skipped; because its
database row is only written at the end, the next run tries it again.
"""

import argparse
import sys
import time
from collections import deque
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from extract_data.cli import add_ocr_options
from extract_data.reading import gpu
from extract_data.runlog import RECENT, Tee, estimate_remaining, format_duration, log_name, progress_line
from extract_data.storage import database, ionos
from extract_data.storage.accounts import save_filings


def build_parser():
    parser = argparse.ArgumentParser(description="Download, OCR and upload Companies House accounts PDFs.")
    parser.add_argument("--limit", type=int,
                        help=f"most filings to do this run (default and highest: {database.MAX_PER_RUN})")
    parser.add_argument("--min-pages", type=int, default=database.MIN_PAGES,
                        help="skip filings with fewer pages than this (default: %(default)s)")
    parser.add_argument("--since", type=int, metavar="YEAR",
                        help="skip filings from before this year, for example --since 2020")
    parser.add_argument("--newest-first", action="store_true",
                        help="do the most recently filed accounts first (default: by filing id)")
    parser.add_argument("--log-dir", default="logs", help="folder for the log of this run (default: %(default)s)")
    parser.add_argument("--work-dir", default="downloads", help="folder for the local PDFs, text and OCR cache")
    add_ocr_options(parser)
    parser.add_argument("--dry-run", action="store_true",
                        help="download and OCR only: no bucket keys needed, nothing uploaded, no database rows")
    return parser


def run(args, results):
    """Do the work of one run.  Each finished filing is added to `results` as (filing id, error or None)."""
    client = None if args.dry_run else ionos.make_client()  # fail early if the bucket keys are missing
    connection = database.connect()
    try:
        filings = database.pending_filings(connection, args.limit, args.min_pages, args.since, args.newest_first)
        print(f"{len(filings)} filing(s) to save")
        if len(filings) == database.MAX_PER_RUN:
            print(f"That is the most one run does ({database.MAX_PER_RUN}); run again for the rest.")
        started = previous = time.monotonic()
        gaps = deque(maxlen=RECENT)
        for filing_id, error in save_filings(filings, args.work_dir, client, connection, args.dpi, args.dry_run):
            now = time.monotonic()
            gaps.append(now - previous)
            results.append((filing_id, error))
            left = estimate_remaining(gaps, len(filings) - len(results))
            print(progress_line(len(results), len(filings), filing_id, error, now - previous, now - started,
                                args.dry_run, left))
            previous = now
        if results:
            total = time.monotonic() - started
            failed = sum(error is not None for _, error in results)
            print(f"Finished {len(results)} filing(s) in {format_duration(total)} "
                  f"({format_duration(total / len(results))} each), {failed} failed")
    finally:
        connection.close()


def main(argv=None):
    args = build_parser().parse_args(argv)
    started = datetime.now()
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    running = log_dir / log_name(started)
    results = []
    try:
        with open(running, "w", encoding="utf-8") as log, redirect_stdout(Tee(sys.stdout, log)):
            print(f"Started {started:%Y-%m-%d %H:%M:%S}  options: {' '.join(sys.argv[1:]) or '(none)'}")
            with gpu.setting(not args.cpu):
                run(args, results)
    finally:                                    # also when the run is stopped (Ctrl+C) or fails part way
        failed = [filing_id for filing_id, error in results if error is not None]
        running.replace(log_dir / log_name(started, len(results), len(failed)))
    if failed:
        sys.exit(f"{len(failed)} filing(s) failed: {failed}")


if __name__ == "__main__":
    main()
