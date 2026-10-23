"""
Extract and process Companies House accounts PDFs.

1. OCR: render each PDF page to an image
2. Run RapidOCR on every image
3. Regroup the detected text fragments into visual rows, so a table row such as
   "Assets 1,000 100" stays on one line
4. Cache the result as JSON so the OCR step only runs once per PDF

Output of this module:
A list of pages
Each page is a list of rows
Each row is a list of (x_position, text) sorted left to right
"""

import json
from pathlib import Path
import pymupdf  # PyMuPDF: opens the PDF and renders pages to pixel images
from rapidocr_onnxruntime import RapidOCR

def render_pages(pdf_path, dpi=300):
    """
    Render every page of the PDF to PNG bytes for OCR.
    DPI default is 300, which is a good balance for OCR, going lower may make small table digits unreliable
    """
    with pymupdf.open(pdf_path) as doc:
        # get_pixmap handles the points-to-pixels scaling
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]

def group_into_rows(detections, y_tolerance_ratio=0.6):
    """
    Group OCR detections that sit on the same visual line into rows.
    RapidOCR returns each text fragment as (box, text, confidence), where box is four (x, y) corners.
    Returns a list of rows, each a list of (x_left, text) sorted left to right.
    """
    line = []
    for box, text, _conf in detections:
        xs = [p[0] for p in box]
        vs = [p[1] for p in box]
        line.append({
            "x": min(xs),                    # leftmost x position
            "vc": (min(vs) + max(vs)) / 2,   # vertical centre
            "h": max(vs) - min(vs),          # fragment height
            "text": text.strip(),            # text content
        })

    # Process the page fragments into rows top to bottom
    line.sort(key=lambda f: f["vc"])

    rows = []  # each entry: {"vc": centre, "h": height, "items": [...]}

    for l in line:
        # Try to find an existing row that this fragment belongs to
        for row in rows:
            if abs(l["vc"] - row["vc"]) < y_tolerance_ratio * row["h"]:
                row["items"].append((l["x"], l["text"]))
                # Update the running centre and height of the row
                n = len(row["items"])
                row["vc"] = (row["vc"] * (n - 1) + l["vc"]) / n
                row["h"] = max(row["h"], l["h"])
                break
        else:
            # No existing row found, create a new one
            rows.append({"vc": l["vc"], "h": l["h"], "items": [(l["x"], l["text"])]})

    # Sort the rows top to bottom, then sort each row's items left to right
    rows.sort(key=lambda r: r["vc"])

    return [sorted(row["items"] for row in rows)]

def ocr_page(engine, page_image):
    """
    Run RapidOCR on a single page image and return its text rows
    Each fragment is a tuple of (box, text, confidence).
    """
    result, _elapsed = engine(page_image)
    return group_into_rows(result or [])

def ocr_pdf(pdf_path, out_dir, dpi=300, use_cache=True):
    """
    Run OCR on every page of the PDF and return a list of pages.
    Each page is a list of rows, each row is a list of (x_position, text) sorted left to right.
    Cache the result as JSON so the OCR step only runs once per PDF.
    """
    # Convert paths to Path objects
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir)
    # Create the output directory if it doesn't exist
    out_dir.mkdir(parents=True, exist_ok=True)
    # Define the cache file path based on the PDF name
    cache_file = out_dir / f"{pdf_path.stem}.ocr.json"

    # If caching is enabled and the cache file exists, load the cached OCR result
    if use_cache and cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # Render pages to images
    pages_images = render_pages(pdf_path, dpi=dpi)

    # Initialise RapidOCR engine
    # Text score is the minimum confidence for text to be considered valid
    # box_thresh is the minimum confidence for detection.
    # Unclip ratio is the ratio for unclipping the detected text.
    # Lowering text_score and box_thresh may increase recall but also false positives.
    engine = RapidOCR(text_score=0.2, box_thresh=0.3, unclip_ratio=2.0)

    # Run OCR on each page
    pages = [ocr_page(engine, img) for img in pages_images]

    # Save the OCR result to the cache file
    cache_file.write_text(json.dumps(pages, indent=2, ensure_ascii=False), encoding="utf-8")

    return pages

def rows_to_lines(rows):
    """
    Convert a list of rows (each a list of (x_position, text)) into plain text lines.
    Each line is the concatenation of the text fragments in that row, separated by spaces.
    """
    return ["  ".join(text for _, text in row) for row in rows]
