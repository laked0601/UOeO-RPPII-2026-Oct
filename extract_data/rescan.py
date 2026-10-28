"""
Re-reading the pages whose totals did not add up, at a higher resolution.

A total that does not equal the rows above it usually means the OCR misread a digit.
Rather than OCR every page at a high resolution (slow), the whole filing is read once at
the normal resolution and only the pages that raised a warning are read again at a higher
one.  A page's new reading is kept only if it reduces the number of warnings, so a rescan
can never make a filing worse.  A genuine error in the filing itself stays flagged: it is
tried once and remembered, so later runs do not repeat the work.
"""

import json
from extract_data.parsing.document import extract_document
from extract_data.reading.ocr import REREAD_DPI, working_file
from pathlib import Path

DEFAULT_RESCAN_DPI = REREAD_DPI  # 1.5 times the normal 300: sharper small digits without huge images


def tried_path(pdf_path, out_dir):
    """The small file that remembers which pages were already rescanned."""
    return working_file(out_dir, Path(pdf_path).stem, ".rescan.json")


def read_record(path):
    """The stored (dpi, pages) of a rescan record; (0, empty set) if missing or unreadable."""
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        pages = {n for n in record.get("pages_tried", []) if isinstance(n, int)}
        dpi = record.get("dpi", 0)
        return (dpi if isinstance(dpi, int) else 0), pages
    except (OSError, ValueError, AttributeError, TypeError):
        return 0, set()


def load_tried(path, dpi=0):
    """
    Page numbers already rescanned (empty if the file is missing or unreadable).

    Pages tried at a lower resolution than `dpi` are not counted, so asking for a higher
    --rescan-dpi gives them another go.
    """
    recorded_dpi, pages = read_record(path)
    return pages if recorded_dpi >= dpi else set()


def save_tried(path, dpi, pages):
    """
    Remember that `pages` were rescanned at `dpi`, keeping earlier pages tried at that same
    resolution (a run that ignored the record must not erase it).
    """
    recorded_dpi, earlier = read_record(path)
    if recorded_dpi == dpi:
        pages = set(pages) | earlier
    Path(path).write_text(json.dumps({"dpi": dpi, "pages_tried": sorted(pages)}), encoding="utf-8")


def rescan_flagged_pages(pages, source_file, rescan, tried=()):
    """
    Extract the document, rescanning pages whose totals did not add up.

    `rescan(numbers)` returns {page number: new rows} for the numbered pages (see
    ocr.reocr_pages); `tried` holds pages rescanned on an earlier run, which are not repeated.
    Returns (pages, result, rescanned, improved): the pages to keep, the extraction of
    them, and the page numbers that were rescanned and that were improved by it.
    """
    flagged = set()
    result = extract_document(pages, source_file, flagged_pages=flagged)
    todo = sorted(flagged - set(tried))
    if not todo:
        return pages, result, [], []

    new_rows = rescan(todo)
    improved = []
    for number in todo:
        if number not in new_rows:
            continue  # e.g. a page with a text layer
        candidate = pages[:number - 1] + [new_rows[number]] + pages[number:]
        better = extract_document(candidate, source_file)
        if len(better["warnings"]) < len(result["warnings"]):
            pages, result = candidate, better
            improved.append(number)
    return pages, result, todo, improved
