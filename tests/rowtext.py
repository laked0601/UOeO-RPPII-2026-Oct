"""A helper for tests: a row of OCR fragments written as text."""

import re

NUMBER = re.compile(r"[\d,.()\- ]+")
RIGHT_EDGE, COLUMN_WIDTH = 1000, 150


def text_row(line):
    """
    The fragments of a row from a text where pieces are separated by two spaces.  Positions are made up:
    text pieces run from the left, figures sit in columns counted from the right edge, so figures
    of different rows line up as they do on a page.
    """
    pieces = [piece.strip() for piece in line.split("  ") if piece.strip()]
    figures = sum(bool(NUMBER.fullmatch(piece)) for piece in pieces)
    fragments, left, column = [], 0, figures
    for piece in pieces:
        if NUMBER.fullmatch(piece):
            right = RIGHT_EDGE - COLUMN_WIDTH * (column - 1)
            fragments.append((right - 10 * len(piece), piece, right))
            column -= 1
        else:
            fragments.append((left, piece, left + 10 * len(piece)))
            left += 10 * len(piece) + 30
    return fragments
