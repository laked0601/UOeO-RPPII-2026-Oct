"""
Extract and process Companies House accounts PDFs.

1. If a page has a text layer (a digital PDF rather than a scan), read the words
   straight from it: this is exact, with no OCR misreads, and much faster
2. Otherwise OCR: render the page to an image and run RapidOCR on it
   (the choice is made page by page, so a mixed PDF works)
3. Regroup the detected text fragments into visual rows, so a table row such as
   "Assets 1,000 100" stays on one line
4. Cache the result as JSON so the OCR step only runs once per PDF

Output of this module:
A list of pages
Each page is a list of rows
Each row is a list of (x_left, text, x_right) sorted left to right
"""

import json
import re
from pathlib import Path

import numpy as np
import pymupdf  # PyMuPDF: opens the PDF and renders pages to pixel images
from rapidocr_onnxruntime import RapidOCR

from extract_data.jsonio import write_json
from extract_data.parsing.rows import to_lines
from extract_data.reading import gpu

# A page needs at least this many words in its text layer to be trusted.  Scans made by
# tiff2pdf have none; a page number or stamp on an otherwise scanned page is only a few.
MIN_TEXT_WORDS = 30
# Words closer together than this fraction of their height belong to one fragment
# ("Cost of sales"); the wide gaps between table columns start a new fragment.
WORD_GAP_RATIO = 0.6
DEFAULT_DPI = 300  # a good balance for OCR; lower makes small table digits unreliable
# A scanned page is read again at REREAD_DPI if the OCR is unsure of some of its text: a piece of text of
# at least DOUBTFUL_MIN_CHARS characters whose confidence is below DOUBTFUL_SCORE (garbled lines score
# about 0.3, ordinary text 0.8 or more).  Short pieces such as page numbers are always a little unsure.
REREAD_DPI = 450
DOUBTFUL_SCORE = 0.5
DOUBTFUL_MIN_CHARS = 3
# RapidOCR can turn each line of text the right way up before reading it (the "angle classifier").  On upright
# pages, which nearly all scans are, it sometimes turns a line upside down by mistake and costs time:
# on 120 scanned pages it left 36 doubtful lines against 2 without it, and took 14% longer.  So it is
# only used for a page that reads badly without it, which is what an upside-down scan does: at least
# UNREADABLE_MIN doubtful pieces of text, and more than half of all its pieces.
UNREADABLE_MIN = 5
# The OCR often reads the pound sign as "f": "f127,964", "f 461,856", "(2014 - f 488,644 )".
POUND_SIGN = re.compile(r"(?<![A-Za-z0-9])f(?=\s?\d)")


def render_page(page, dpi=DEFAULT_DPI):
    """
    Render one PDF page to an image array for OCR.
    The raw pixels are handed over as they are: encoding them as a PNG and decoding it again gave the
    OCR exactly the same image, at a fifth of the total time.
    """
    # get_pixmap handles the points-to-pixels scaling
    pixmap = page.get_pixmap(dpi=dpi)
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)


def text_layer_rows(page):
    """
    The rows of a page read from its text layer, or None if it has too little text (a scan).

    The result has the same shape as the OCR result: rows of (x_left, text, x_right).
    PyMuPDF returns single words, so neighbouring words on one line are joined into
    fragments the way OCR phrases would be, and a wide gap (the space between table
    columns) starts a new fragment.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word number)
    if len(words) < MIN_TEXT_WORDS:
        return None

    lines = {}
    for x0, y0, x1, y1, word, block, line, _ in words:
        lines.setdefault((block, line), []).append((x0, y0, x1, y1, word))

    detections = []  # one (box, text, confidence) per fragment, as RapidOCR gives
    for line in lines.values():
        line.sort()
        group = [line[0]]
        for word in line[1:]:
            previous = group[-1]
            if word[0] - previous[2] <= WORD_GAP_RATIO * (previous[3] - previous[1]):
                group.append(word)
                continue
            detections.append(fragment_box(group))
            group = [word]
        detections.append(fragment_box(group))
    return group_into_rows(detections)


def fragment_box(words):
    """Join the words of one fragment into a RapidOCR-style (box, text, confidence) detection."""
    x0, x1 = words[0][0], words[-1][2]
    y0, y1 = min(w[1] for w in words), max(w[3] for w in words)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], " ".join(w[4] for w in words), 1.0


def group_into_rows(detections, y_tolerance_ratio=0.6):
    """
    Group OCR detections that sit on the same visual line into rows.
    RapidOCR returns each text fragment as (box, text, confidence), where box is four (x, y) corners.
    Returns a list of rows, each a list of (x_left, text, x_right) sorted left to right.
    The horizontal positions let later stages work out which table column a figure
    sits under, even when neighbouring cells in its row are blank.
    """
    fragments = []
    for box, text, _conf in detections:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        fragments.append({
            "x": min(xs),  # leftmost x position
            "x2": max(xs),  # rightmost x position
            "vc": (min(ys) + max(ys)) / 2,  # vertical centre
            "h": max(ys) - min(ys),  # fragment height
            "text": text.strip(),  # text content
        })
    fragments.sort(key=lambda f: f["vc"])  # top to bottom

    rows = []  # each entry: {"vc": centre, "h": height, "items": [...]}
    for fragment in fragments:
        item = (fragment["x"], fragment["text"], fragment["x2"])
        row = next((r for r in rows if abs(fragment["vc"] - r["vc"]) < y_tolerance_ratio * r["h"]), None)
        if row is None:
            rows.append({"vc": fragment["vc"], "h": fragment["h"], "items": [item]})
            continue
        # Add it to the row it sits on, and move the row's running centre and height
        row["items"].append(item)
        n = len(row["items"])
        row["vc"] = (row["vc"] * (n - 1) + fragment["vc"]) / n
        row["h"] = max(row["h"], fragment["h"])

    rows.sort(key=lambda r: r["vc"])
    return [sorted(row["items"]) for row in rows]


def fix_pound_signs(text):
    """Put back the pound sign the OCR read as an "f" in front of a figure."""
    return POUND_SIGN.sub("£", text)


def ocr_page_scored(engine, page_image, classify=False):
    """
    Run RapidOCR on a single page image, with the angle classifier on if `classify`; returns (rows, doubtful).
    Each detected fragment is a tuple of (box, text, confidence).  `doubtful` counts the fragments
    the OCR was unsure of (see DOUBTFUL_SCORE), which shows the page may be worth reading again.
    """
    engine.use_angle_cls = classify
    result, _elapsed = engine(page_image)
    detections = [(box, fix_pound_signs(text), confidence) for box, text, confidence in result or []]
    doubtful = sum(1 for _, text, confidence in detections
                   if float(confidence) < DOUBTFUL_SCORE and len(text.strip()) >= DOUBTFUL_MIN_CHARS)
    return group_into_rows(detections), doubtful


def mostly_unreadable(rows, doubtful):
    """True if most of the page read badly, which is how an upside-down scan looks to the OCR."""
    pieces = sum(len(row) for row in rows)
    return doubtful >= UNREADABLE_MIN and doubtful * 2 > pieces


def make_engine():
    """
    Create the RapidOCR engine (on the GPU when gpu.py says so).
    Text score is the minimum confidence for text to be considered valid
    box_thresh is the minimum confidence for detection.
    Unclip ratio is the ratio for unclipping the detected text.
    Lowering text_score and box_thresh may increase recall but also false positives.
    """
    with gpu.cuda_config():
        return RapidOCR(text_score=0.2, box_thresh=0.3, unclip_ratio=2.0)


_engines = {}  # the engines made so far, by whether they run on the GPU


def shared_engine():
    """
    The OCR engine, made once and then reused: loading the three models takes about half a second,
    which added up over thousands of filings.  The GPU setting can change (--cpu), so there is one per setting.
    """
    on_gpu = gpu.in_use()
    if on_gpu not in _engines:
        _engines[on_gpu] = make_engine()
    return _engines[on_gpu]


def working_file(out_dir, stem, suffix):
    """Path of a working file (OCR cache, rescan record) in the `cache` folder inside `out_dir`,
    so the output folder itself holds only results."""
    folder = Path(out_dir) / "cache"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{stem}{suffix}"


def cache_path(pdf_path, out_dir):
    """Where the OCR result of a PDF is cached."""
    return working_file(out_dir, Path(pdf_path).stem, ".ocr.json")


def save_cache(pdf_path, out_dir, pages):
    """Write the pages to the OCR cache file."""
    write_json(cache_path(pdf_path, out_dir), pages)


def read_page(engine, page, dpi, reread):
    """
    OCR one page; returns (rows, was_reread).

    A page that reads badly is tried again with the angle classifier (it may be upside down).  With
    `reread`, a page the OCR is still unsure of is read again at REREAD_DPI.  Each time, the reading
    with fewer doubtful pieces of text is kept, so trying again can never make a page worse.
    """
    image = render_page(page, dpi=dpi)
    rows, doubtful = ocr_page_scored(engine, image)
    classify = False
    if mostly_unreadable(rows, doubtful):
        turned, fewer = ocr_page_scored(engine, image, classify=True)
        if fewer < doubtful:
            rows, doubtful, classify = turned, fewer, True
    if not (reread and doubtful and REREAD_DPI > dpi):
        return rows, False
    better, fewer = ocr_page_scored(engine, render_page(page, dpi=REREAD_DPI), classify)
    return (better, True) if fewer < doubtful else (rows, False)


def read_scanned(doc, numbers, dpi, reread=True):
    """
    OCR the given pages (numbered from 0) of an open PDF; returns {page number: rows}.

    See read_page for the pages that are read again.  Pages that read cleanly stay at the normal
    resolution, which keeps the run fast.

    Pages are read one at a time on purpose: onnxruntime already uses every CPU core for a single
    page, and a test with four worker processes on a 27-page filing was slower (211s against 167s).
    Three worker threads sharing the engine were slower too (55s against 36s for 46 pages).
    """
    if not numbers:
        return {}
    engine = shared_engine()
    print(f"  OCR on the {'GPU' if gpu.in_use() else 'CPU'}: {len(numbers)} pages")
    pages, reread_numbers = {}, []
    for number in numbers:
        pages[number], was_reread = read_page(engine, doc[number], dpi, reread)
        if was_reread:
            reread_numbers.append(number + 1)
    if reread_numbers:
        print(f"  Re-read pages {reread_numbers} at {REREAD_DPI} dpi (the OCR was unsure of some text)")
    return pages


def read_pages(pdf_path, dpi, use_text_layer):
    """Read every page: from the text layer where there is one, otherwise by OCR."""
    pages, to_ocr = [], []  # to_ocr: numbers of the pages with no text layer
    with pymupdf.open(pdf_path) as doc:
        for number, page in enumerate(doc):
            rows = text_layer_rows(page) if use_text_layer else None
            pages.append(rows)
            if rows is None:
                to_ocr.append(number)
        for number, rows in read_scanned(doc, to_ocr, dpi).items():
            pages[number] = rows
    print(f"{Path(pdf_path).name}: {len(pages) - len(to_ocr)} of {len(pages)} pages read from the text layer, "
          f"{len(to_ocr)} by OCR")
    return pages


def is_scan(page):
    """True if the page has no usable text layer, so it has to be OCRed."""
    return len(page.get_text("words")) < MIN_TEXT_WORDS


def reocr_pages(pdf_path, numbers, dpi):
    """
    OCR the given pages (numbered from 1) again at `dpi`; return {page number: rows}.

    Pages with a text layer are skipped: their text is exact, so a rescan cannot improve it.
    """
    with pymupdf.open(pdf_path) as doc:
        scanned = [n - 1 for n in numbers if is_scan(doc[n - 1])]
        rows = read_scanned(doc, scanned, dpi, reread=False)
    return {number + 1: page for number, page in rows.items()}


def ocr_pdf(pdf_path, out_dir, dpi=DEFAULT_DPI, use_cache=True, use_text_layer=True):
    """
    Read every page of the PDF and return a list of pages.
    Each page is a list of rows, each row is a list of (x_left, text, x_right) sorted left to right.
    A page with a text layer is read directly (unless use_text_layer is False); any other
    page is OCRed.  Cache the result as JSON so this only runs once per PDF.
    """
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_path(pdf_path, out_dir)

    if use_cache and cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))

    pages = read_pages(pdf_path, dpi, use_text_layer)
    save_cache(pdf_path, out_dir, pages)
    return pages


def write_text_dump(pages, path):
    """Raw text, page by page, so a human can compare it against the original scan."""
    raw = "\n".join(f"PAGE {i}\n" + "\n".join(to_lines(page)) for i, page in enumerate(pages, 1))
    path.write_text(raw, encoding="utf-8")
