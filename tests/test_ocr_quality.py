"""
Tests for the OCR clean-up in extract_data.reading.ocr: the pound sign and the re-read of doubtful pages.

The OCR engine is a fake that answers by the resolution of the page it is given, so no models are needed.
"""

from extract_data.reading import gpu, ocr

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
