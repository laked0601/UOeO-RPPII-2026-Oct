"""
Tests for how a PDF is read in extract_data.reading: the text layer, the OCR clean-up and the GPU switch.

PDFs are built in memory with PyMuPDF and the OCR engine is replaced by a fake that answers by the resolution
of the page it is given, so the tests are quick and need no OCR models.
"""

import json

import pymupdf
import pytest

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


def test_a_cache_cut_short_by_a_stopped_run_is_ignored_and_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "RapidOCR", FakeEngine)
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    cache = ocr.cache_path(pdf, tmp_path / "out")
    cache.write_text("[[[[0, \"Tang", encoding="utf-8")  # what a run stopped part way would leave
    pages = ocr.ocr_pdf(pdf, tmp_path / "out")
    assert len(pages) == 2
    assert json.loads(cache.read_text(encoding="utf-8")) == json.loads(json.dumps(pages))  # tuples are lists in JSON


def test_the_cache_is_written_through_a_temporary_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "RapidOCR", FakeEngine)
    pdf = tmp_path / "mixed.pdf"
    make_mixed_pdf(pdf)
    ocr.ocr_pdf(pdf, tmp_path / "out")
    assert not list((tmp_path / "out").rglob("*.tmp"))


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


BOX = [[0, 0], [100, 0], [100, 10], [0, 10]]


def test_f_in_front_of_a_figure_becomes_a_pound_sign():
    assert ocr.fix_pound_signs("Land at a cost of f127,964 included") == "Land at a cost of £127,964 included"
    assert ocr.fix_pound_signs("(2014 - f 488,644 )") == "(2014 - £ 488,644 )"
    assert ocr.fix_pound_signs("Nominal f1") == "Nominal £1"


def test_other_uses_of_f_are_left_alone():
    for text in ("of 5 pages", "Section 5(f) 2", "Profit f", "if 2015", "F1", "Notes  f  f"):
        assert ocr.fix_pound_signs(text) == text


class SizedEngine:
    """Reads a page as garbled at the normal resolution and cleanly at the higher one."""

    def __init__(self):
        self.sizes = []

    def __call__(self, image):
        width = image[0]  # the "image" is (width, text) from the fake render
        self.sizes.append(width)
        if width >= ocr.REREAD_DPI:
            return [(BOX, "Total equity 265,441", 0.95)], 0
        return [(BOX, "ias e aa oa tr", 0.27), (BOX, "1", 0.3)], 0


def fake_doc(monkeypatch, engine):
    monkeypatch.setattr(ocr, "shared_engine", lambda: engine)
    monkeypatch.setattr(ocr, "render_page", lambda page, dpi: (dpi, page))
    monkeypatch.setattr(gpu, "in_use", lambda: False)
    return {0: "page one"}


def test_a_doubtful_page_is_read_again_and_the_better_reading_kept(monkeypatch):
    engine = SizedEngine()
    pages = ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300)
    assert engine.sizes == [300, ocr.REREAD_DPI]
    assert pages[0][0][0][1] == "Total equity 265,441"


def test_a_re_read_that_is_no_better_is_not_kept(monkeypatch):
    class StillGarbledEngine:
        sizes = []

        def __call__(self, image):
            self.sizes.append(image[0])
            return [(BOX, f"garbled at {image[0]}", 0.27)], 0

    engine = StillGarbledEngine()
    pages = ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300)
    assert engine.sizes == [300, ocr.REREAD_DPI]
    assert pages[0][0][0][1] == "garbled at 300"  # the first reading is kept


def test_short_unsure_text_such_as_a_page_number_does_not_trigger_a_re_read(monkeypatch):
    class PageNumberEngine:
        sizes = []

        def __call__(self, image):
            self.sizes.append(image[0])
            return [(BOX, "Total equity", 0.95), (BOX, "4", 0.3)], 0

    engine = PageNumberEngine()
    ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300)
    assert engine.sizes == [300]


class UpsideDownEngine:
    """Reads a page badly unless the angle classifier is on, as it does with an upside-down scan."""

    def __init__(self):
        self.use_angle_cls = None
        self.calls = []

    def __call__(self, image):
        self.calls.append((image[0], self.use_angle_cls))
        if self.use_angle_cls:
            return [(BOX, f"Total equity {n}", 0.95) for n in range(8)], 0
        return [(BOX, f"ias e aa oa {n}", 0.2) for n in range(8)], 0


def test_an_upright_page_is_read_without_the_classifier(monkeypatch):
    engine = SizedEngine()
    ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300, reread=False)
    assert engine.use_angle_cls is False


def test_a_page_that_reads_badly_is_tried_again_with_the_classifier(monkeypatch):
    engine = UpsideDownEngine()
    pages = ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300)
    assert engine.calls == [(300, False), (300, True)]
    assert pages[0][0][0][1] == "Total equity 0"


def test_a_few_doubtful_pieces_do_not_trigger_the_classifier(monkeypatch):
    class FewDoubtfulEngine:
        calls = []

        def __call__(self, image):
            self.calls.append(self.use_angle_cls)
            return [(BOX, "Total equity", 0.95)] * 20 + [(BOX, "garbled text", 0.2)] * 6, 0

    engine = FewDoubtfulEngine()
    ocr.read_scanned(fake_doc(monkeypatch, engine), [0], 300, reread=False)
    assert engine.calls == [False]


def test_the_setting_is_put_back_after_the_block_even_after_an_error(monkeypatch):
    monkeypatch.setattr(gpu, "enabled", True)
    with gpu.setting(False):
        assert gpu.enabled is False
    assert gpu.enabled is True
    with pytest.raises(RuntimeError), gpu.setting(False):
        raise RuntimeError
    assert gpu.enabled is True
