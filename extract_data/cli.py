"""
Command line options shared by main.py and upload_filings.py.
"""

from extract_data.reading.ocr import DEFAULT_DPI


def add_ocr_options(parser):
    """
    Add the options that say how pages are OCRed.
    """
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="resolution used to OCR scanned pages")
    parser.add_argument("--cpu", action="store_true", help="OCR on the CPU even if a GPU is available")
