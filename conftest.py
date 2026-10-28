import pytest


@pytest.fixture(autouse=True)
def fresh_ocr_engines():
    """Tests swap in fake engines, so none made by an earlier test may be reused."""
    from extract_data.reading import ocr
    ocr._engines.clear()
