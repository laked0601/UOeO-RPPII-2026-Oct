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
(older cache files hold (x_left, text) only; both shapes are accepted downstream)
"""

import json
import pymupdf  # PyMuPDF: opens the PDF and renders pages to pixel images
from extract_data.reading import gpu
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR

# A page needs at least this many words in its text layer to be trusted.  Scans made by
# tiff2pdf have none; a page number or stamp on an otherwise scanned page is only a few.
MIN_TEXT_WORDS = 30
# Words closer together than this fraction of their height belong to one fragment
# ("Cost of sales"); the wide gaps between table columns start a new fragment.
WORD_GAP_RATIO = 0.6
DEFAULT_DPI = 300  # a good balance for OCR; lower makes small table digits unreliable


def render_page(page, dpi=DEFAULT_DPI):
    """
    Render one PDF page to PNG bytes for OCR.
    """
    # get_pixmap handles the points-to-pixels scaling
    return page.get_pixmap(dpi=dpi).tobytes("png")


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


def ocr_page(engine, page_image):
    """
    Run RapidOCR on a single page image and return its text rows
    Each fragment is a tuple of (box, text, confidence).
    """
    result, _elapsed = engine(page_image)
    return group_into_rows(result or [])


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


def ocr_images(images):
    """
    OCR a list of page images and return their rows, in page order.

    Pages are read one at a time on purpose: onnxruntime already uses every CPU core for a single
    page, and a test with four worker processes on a 27-page filing was slower (211s against 167s).
    The engine is created only when there is something to read.
    """
    if not images:
        return []
    engine = make_engine()
    print(f"  OCR on the {'GPU' if gpu.in_use() else 'CPU'}: {len(images)} pages")
    return [ocr_page(engine, image) for image in images]


def cache_file(out_dir, stem, suffix):
    """
    Path of a working file (OCR cache, rescan record) in the `cache` folder inside `out_dir`,
    so the output folder itself holds only results.  A file left beside the results by an
    older version is moved into the cache folder the first time it is looked for.
    """
    folder = Path(out_dir) / "cache"
    folder.mkdir(parents=True, exist_ok=True)
    path, old = folder / f"{stem}{suffix}", Path(out_dir) / f"{stem}{suffix}"
    if old.exists() and not path.exists():
        old.replace(path)
    return path


def cache_path(pdf_path, out_dir):
    """Where the OCR result of a PDF is cached."""
    return cache_file(out_dir, Path(pdf_path).stem, ".ocr.json")


def save_cache(pdf_path, out_dir, pages):
    """Write the pages to the OCR cache file."""
    cache_path(pdf_path, out_dir).write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")


def reocr_pages(pdf_path, numbers, dpi):
    """
    OCR the given pages (numbered from 1) again at `dpi`; return {page number: rows}.

    Pages with a text layer are skipped: their text is exact, so a rescan cannot improve it.
    """
    images = {}
    with pymupdf.open(pdf_path) as doc:
        for number in numbers:
            page = doc[number - 1]
            if text_layer_rows(page) is None:
                images[number] = render_page(page, dpi=dpi)
    return dict(zip(images, ocr_images(list(images.values()))))


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
    cache_file = cache_path(pdf_path, out_dir)

    # If caching is enabled and the cache file exists, load the cached OCR result
    if use_cache and cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    pages = read_pages(pdf_path, dpi, use_text_layer)
    save_cache(pdf_path, out_dir, pages)
    return pages


def read_pages(pdf_path, dpi, use_text_layer):
    """Read every page: from the text layer where there is one, otherwise by OCR."""
    pages, to_ocr = [], []  # to_ocr: (page number, image) for the pages with no text layer
    with pymupdf.open(pdf_path) as doc:
        for number, page in enumerate(doc):
            rows = text_layer_rows(page) if use_text_layer else None
            pages.append(rows)
            if rows is None:
                to_ocr.append((number, render_page(page, dpi=dpi)))

    for (number, _), rows in zip(to_ocr, ocr_images([image for _, image in to_ocr])):
        pages[number] = rows
    print(f"{Path(pdf_path).name}: {len(pages) - len(to_ocr)} of {len(pages)} pages read from the text layer, "
          f"{len(to_ocr)} by OCR")
    return pages


def rows_to_lines(rows):
    """
    Convert a list of rows (each a list of (x_left, text, x_right)) into plain text lines.
    Each line is the text fragments of that row joined by two spaces.
    """
    return ["  ".join(fragment[1] for fragment in row) for row in rows]


def write_text_dump(pages, path):
    """Raw text, page by page, so a human can compare it against the original scan."""
    raw = "\n".join(f"PAGE {i}\n" + "\n".join(rows_to_lines(page)) for i, page in enumerate(pages, 1))
    path.write_text(raw, encoding="utf-8")
