"""
Turning OCR rows into labelled rows of figures.

Each OCR row (a list of positioned fragments) is split into a
label and the figures at its right, with repairs for the commonest OCR damage
(figures glued together, stray marks, labels wrapped over two lines).
"""

import re

from extract_data.parsing.figures import DASH, UNREADABLE, to_number

# Last words that show a label carries on to the next line ("TOTAL ASSETS LESS CURRENT" / "LIABILITIES"),
# and first words of a short line that finishes the label above it ("BEFORE TAXATION").
CONTINUES = {"and", "or", "of", "less", "than", "within", "due", "in", "to", "the", "a", "an", "for", "from",
             "after", "before", "on", "at", "by", "with", "current", "net", "non", "gross"}
TAIL_START = {"before", "after", "for", "the", "of", "per", "to"}
# A figure with thousands separators, "124,556" or "(213, 135)" (the OCR may add a space).
THOUSANDS_FIGURE = r"\(?-?\d{1,3}(?:[.,]\s?\d{3})+\)?"
# Figures at the end of a text fragment: "At 31 March 2025 124,556 7,667." or
# "Cost of sales (213, 135)".  The OCR sometimes merges them into the label.
TRAILING_NUMBERS = re.compile(rf"^(.*?\S)((?:\s+{THOUSANDS_FIGURE}[.,]?)+)$")
# Two or more figures in one fragment, and a single figure within such a run.
NUMBER_IN_RUN = r"\(?-?\d{1,3}(?:[.,;:]\s?\d{3})+\)?|\(?-?\d+\)?"
NUMBER_RUN = re.compile(rf"^(?:{NUMBER_IN_RUN})(?:\s+(?:{NUMBER_IN_RUN}))+$")  # figures separated by spaces


def fragments_of(item):
    """The [text, span] pieces of one OCR row, a list of (x_left, text, x_right)."""
    return [[text.strip(), (left, right)] for left, text, right in item if text.strip()]


def clean_pieces(pieces):
    """
    Clean up what the OCR produced: replacement characters, figures run together
    "(1,234)(5,678)", stray marks (a lone "." or ",", or a dot in front of a word or
    figure).  Dashes (nil figures) and currency symbols are kept.
    """
    for p in pieces:
        p[0] = re.sub(r"\)\s*\(", ") (", p[0].replace("�", "").replace(" ", " ")).strip()
        p[0] = re.sub(r"(?<=\d)[·•'`*_|°\"~^]+$", "", p[0])  # "6,776,115·" -> "6,776,115"
        if not DASH.match(p[0]):
            p[0] = p[0].lstrip(". ,;:|*")
    return [p for p in pieces if re.search(r"[\w£$€]", p[0]) or DASH.match(p[0])]


def sub_span(span, start, end, length):
    """The horizontal extent of characters start..end of a text of `length` characters printed across `span`."""
    width = span[1] - span[0]
    return span[0] + width * start / length, span[0] + width * end / length


def split_number_runs(pieces):
    """Several figures run together in one fragment, "(11,756,310) (12,027,711)": make each its own piece."""
    split = []
    for text, span in pieces:
        if NUMBER_RUN.match(text):
            for number in re.finditer(NUMBER_IN_RUN, text):
                split.append([number.group(0), sub_span(span, number.start(), number.end(), len(text))])
        else:
            split.append([text, span])
    return split


def pop_trailing_figures(pieces):
    """
    Remove the figures from the end of `pieces` (in place); returns (values, tokens, spans).

    A figure that is printed but cannot be read gives a value of None.
    """
    values, tokens, spans = [], [], []
    while pieces:
        text, span = pieces[-1]
        number = to_number(text)
        unreadable = number is None and len(text) >= 5 and UNREADABLE.match(text) and re.search(r"[.,]", text)
        if number is None and not unreadable:
            break
        pieces.pop()
        values.insert(0, None if unreadable else number)
        tokens.insert(0, text.strip())
        spans.insert(0, span)
    return values, tokens, spans


def pop_figures_merged_into_label(pieces, values, tokens, spans):
    """
    The OCR sometimes merges the figures into the label: "At 31 March 2025 124,556 7,667."
    Split them off the last piece and put them in front of `values`, `tokens` and `spans`.
    """
    m = TRAILING_NUMBERS.match(pieces[-1][0]) if pieces else None
    if not m:
        return
    text, span = pieces.pop()
    pieces.append([m.group(1), sub_span(span, 0, len(m.group(1)), len(text))])
    found = re.finditer(THOUSANDS_FIGURE, m.group(2))
    for number in reversed(list(found)):
        start, end = m.start(2) + number.start(), m.start(2) + number.end()
        values.insert(0, to_number(number.group(0)))
        tokens.insert(0, number.group(0))
        spans.insert(0, sub_span(span, start, end, len(text)))


def take_figures(pieces):
    """
    Remove the figures from the end of `pieces` (in place) and return them.

    Returns (values, tokens, spans): the numbers, the text as printed, and the horizontal
    extents.  A figure that is printed but cannot be read gives a value of None.
    """
    values, tokens, spans = pop_trailing_figures(pieces)
    pop_figures_merged_into_label(pieces, values, tokens, spans)
    return values, tokens, spans


def finishes_label_above(previous, row):
    """
    A short line that finishes the label of the figures above it
    ("SURPLUS ... ON ORDINARY ACTIVITIES  64,364" / "BEFORE TAXATION").
    """
    first_word = row["label"].split(" ")[0].lower() if row["label"] else ""
    return bool(previous and previous["values"] and not row["values"] and len(row["frags"]) == 1
                and len(row["label"]) <= 30 and first_word in TAIL_START
                and not row["label"].endswith((".", ":")))


def continues_label_above(previous, row):
    """
    A label that wrapped onto a second line.  The first line has no figures and either
    ends in a joining word ("TOTAL ASSETS LESS CURRENT") or the second starts in lower
    case.  The second line holds the figures, or is a single piece of text; multi-piece
    column headings are left alone.
    """
    if not (previous and not previous["values"] and previous["label"]
            and (row["values"] or len(row["frags"]) == 1)):
        return False
    last_word = re.sub(r"\W", "", previous["label"].split(" ")[-1].lower())
    return (row["label"][:1].islower() or last_word in CONTINUES) and not previous["label"].endswith(
        ":")  # "Represented by:" is a heading


def joined_text(first, second):
    """The text pieces, their positions and the label of `first` followed by those of `second`."""
    return {"frags": first["frags"] + second["frags"], "fx": first["fx"] + second["fx"],
            "label": first["label"] + " " + second["label"]}


def read_rows(source):
    """
    Split OCR rows into dicts with the label and the figures at the right.

    `source` is one page: a list of rows, each a list of OCR fragments (x_left, text, x_right).
    Each returned row has:
      frags / fx    the text pieces, and their horizontal extents
      label         the text in front of the figures
      values        the figures, as numbers
      tokens / vx   the figures as printed, and their horizontal extents
    A label that wrapped onto a second line is re-joined.
    """
    rows = []
    for item in source:
        pieces = split_number_runs(clean_pieces(fragments_of(item)))
        values, tokens, spans = take_figures(pieces)
        texts = [t for t, _ in pieces]
        row = {"frags": texts, "fx": [s for _, s in pieces], "label": " ".join(texts),
               "values": values, "tokens": tokens, "vx": spans}

        previous = rows[-1] if rows else None
        if finishes_label_above(previous, row):
            previous.update(joined_text(previous, row))  # the short line finishes the label above it
            continue
        if continues_label_above(previous, row):
            rows.pop()
            row.update(joined_text(previous, row))  # keeps this row's figures
        rows.append(row)
    return rows


def to_lines(page):
    """The rows of a page as plain text lines: the fragments of each row joined by two spaces."""
    return ["  ".join(fragment[1] for fragment in row) for row in page]
