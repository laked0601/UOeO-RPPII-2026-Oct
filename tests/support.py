"""Helpers shared by the tests."""

import json
import re
from pathlib import Path

from extract_data.parsing.document import extract_document

FIXTURES = Path(__file__).parent / "fixtures"
NUMBER = re.compile(r"[\d,.()\- ]+")
RIGHT_EDGE, COLUMN_WIDTH = 1000, 150


def load_pages(name):
    """The saved OCR output of a real filing (see tests/fixtures)."""
    return json.loads((FIXTURES / f"{name}.ocr.json").read_text(encoding="utf-8"))


def extract(name):
    """The extraction of a saved filing."""
    return extract_document(load_pages(name), f"{name}.pdf")


def table(result, name):
    return next(t for t in result["statements"] + result["note_tables"] if t["name"] == name)


def row(t, label, nth=0):
    return [r for r in t["rows"] if r["label"] == label][nth]


def figures(r):
    return list(r["values"].values())


def text_row(line):
    """
    The fragments of a row from a text where pieces are separated by two spaces.  Positions are made up:
    text pieces run from the left, figures sit in columns counted from the right edge, so figures
    of different rows line up as they do on a page.
    """
    pieces = [piece.strip() for piece in line.split("  ") if piece.strip()]
    columns = sum(bool(NUMBER.fullmatch(piece)) for piece in pieces)
    fragments, left = [], 0
    for piece in pieces:
        if NUMBER.fullmatch(piece):
            right = RIGHT_EDGE - COLUMN_WIDTH * (columns - 1)
            fragments.append((right - 10 * len(piece), piece, right))
            columns -= 1
        else:
            fragments.append((left, piece, left + 10 * len(piece)))
            left += 10 * len(piece) + 30
    return fragments
