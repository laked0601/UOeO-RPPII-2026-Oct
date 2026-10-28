"""
Tests for reading a PDF's text layer instead of OCR (extract_data.ocr).

PDFs are built in memory with PyMuPDF; the OCR engine is replaced by a fake so
the tests are quick and do not need the OCR models.
"""

import pymupdf

from extract_data.parsing.document import extract_document
from extract_data.reading import gpu, ocr

LABELS = ["BALANCE SHEET", "Tangible assets", "Cash at bank and in hand", "Net assets"] + [f"Row {i}" for i in
                                                                                           range(12)]


def digital_page(doc):
    """A page with a text layer: labels at the left, two figure columns at the right."""
    page = doc.new_page()
    for i, label in enumerate(LABELS):
        y = 60 + i * 18
        page.insert_text((60, y), label, fontsize=10)
        if i >= 1:
            page.insert_text((380, y), f"{1000 + i:,}", fontsize=10)
            page.insert_text((470, y), f"{900 + i:,}", fontsize=10)
    return page


def test_text_layer_rows_keep_phrases_together_and_columns_apart():
    doc = pymupdf.open()
    page = digital_page(doc)
    rows = ocr.text_layer_rows(page)
    row = next(r for r in rows if r[0][1] == "Cash at bank and in hand")
    assert [f[1] for f in row] == ["Cash at bank and in hand", "1,002", "902"]
    assert row[0][0] < row[1][0] < row[2][0]  # (x_left, text, x_right), left to right
    assert all(len(f) == 3 for r in rows for f in r)


def test_page_without_text_returns_none():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 60), "Page 3", fontsize=10)  # a stamp is not a text layer
    assert ocr.text_layer_rows(page) is None


class FakeEngine:
    calls = 0

    def __init__(self, **_):
        pass

    def __call__(self, image):
        FakeEngine.calls += 1
        box = [[10, 10], [200, 10], [200, 30], [10, 30]]
        return [(box, "SCANNED PAGE", 0.99)], 0.0


def make_mixed_pdf(path):
    doc = pymupdf.open()
    digital_page(doc)
    doc.new_page()  # blank: must be OCRed
    doc.save(path)


def test_mixed_pdf_reads_text_pages_directly_and_ocrs_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "RapidOCR", FakeEngine)
    FakeEngine.calls = 0
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    pages = ocr.ocr_pdf(pdf, tmp_path / "out")
    assert FakeEngine.calls == 1  # only the blank page
    assert any(f[1] == "Tangible assets" for r in pages[0] for f in r)
    assert [f[1] for r in pages[1] for f in r] == ["SCANNED PAGE"]


def test_force_ocr_ignores_the_text_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "RapidOCR", FakeEngine)
    FakeEngine.calls = 0
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    ocr.ocr_pdf(pdf, tmp_path / "out", use_text_layer=False)
    assert FakeEngine.calls == 2


def test_text_layer_rows_feed_the_extractor():
    doc = pymupdf.open()
    page = digital_page(doc)
    result = extract_document([ocr.text_layer_rows(page)], source_file="x.pdf")
    statement = result["statements"][0]
    row = next(r for r in statement["rows"] if r["label"] == "Cash at bank and in hand")
    assert sorted(v for v in row["values"].values() if v) == [902, 1002]


def test_engine_stays_on_the_cpu_when_the_gpu_is_switched_off_or_missing(monkeypatch):
    monkeypatch.setattr(ocr, "RapidOCR", FakeEngine)
    monkeypatch.setattr(gpu, "available", lambda: True)
    monkeypatch.setattr(gpu, "enabled", False)  # --cpu
    assert isinstance(ocr.make_engine(), FakeEngine)
    monkeypatch.setattr(gpu, "enabled", True)
    monkeypatch.setattr(gpu, "available", lambda: False)  # CPU-only onnxruntime installed
    assert isinstance(ocr.make_engine(), FakeEngine)
