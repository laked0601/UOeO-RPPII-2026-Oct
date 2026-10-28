"""
The columns of a table, worked out from its header rows.

A header row is a list of (text, x_left, x_right).
`build_columns` turns the stacked header rows ("Consolidated" / "2025" / "$ million") into one description per column.
`column_base` gives each column a key for its period end date (or year, or text).
`column_qualifier` give each column the key its figures are stored under.
"""

import re
from datetime import timedelta

from extract_data.parsing.figures import UNITS, find_dates

STATUS = re.compile(r"\b(unaudited|audited|restated)\b", re.I)
# Headings that cover several columns ("Group" over its 2025 and 2024 columns).
SPAN_WORDS = {"group", "company", "consolidated", "llp", "parent", "charity", "association"}


def header_from(texts, spans):
    """Build a header row from text pieces and their horizontal extents."""
    return [(text, *span) for text, span in zip(texts, spans)]


def parse_column(text, x1=None, x2=None):
    """Describe one column from its header text (dates, year, audit status, position)."""
    text = re.sub(r"\bS(?=\s*(?:million|mn|bn|000))", "$", text)  # OCR: "S million" -> "$ million"
    dates = find_dates(text)
    if dates and dates[-1].day == 1 and re.match(r"\s*at\b", text, re.I):
        dates[-1] -= timedelta(days=1)  # "At 1 January 2025" is the balance at the end of 2024
    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    status = STATUS.search(text)
    return {"text": text,
            "period_end": dates[-1] if dates else None,
            "year": int(years[-1]) if years else None,
            "status": status.group(1).capitalize() if status else None,
            "x": (x1, x2) if x1 is not None else None}


def spans_columns(piece_row, base):
    """Is this header line made only of group words ("Group  Company") over more columns than it has?"""
    return (2 <= len(piece_row) < len(base)
            and all(re.sub(r"\W", "", p[0]).lower() in SPAN_WORDS for p in piece_row))


def target_columns(centre, centres):
    """
    The columns a header piece belongs to, given its centre and the column centres.

    Normally the nearest one; a heading centred between two columns ("Group" over 2025 and
    2024) belongs to both.
    """
    order = sorted(range(len(centres)), key=lambda i: abs(centres[i] - centre))
    targets = [order[0]]
    if len(order) > 1:
        first, second = order[0], order[1]
        gap = abs(centres[first] - centres[second])
        distances = abs(centre - centres[first]), abs(centre - centres[second])
        if sum(distances) <= gap * 1.05 and min(distances) >= gap * 0.3:
            targets.append(second)
    return targets


def positioned_columns(header_rows, base):
    """
    Columns built from the header pieces: each piece joins its nearest column.
    """
    centres = [(p[1] + p[2]) / 2 for p in base]
    parts = [[] for _ in base]
    for r in header_rows:  # includes one-piece lines such as "Plant and"
        if spans_columns(r, base):
            # "Group  Company" over four year columns: each such heading covers the columns that
            # are nearest to it, not just one.
            for column, centre in enumerate(centres):
                nearest = min(r, key=lambda p: abs((p[1] + p[2]) / 2 - centre))
                parts[column].append(nearest[0])
            continue
        for text, x1, x2 in r:
            for target in target_columns((x1 + x2) / 2, centres):
                parts[target].append(text)
    return [parse_column(" ".join(p), b[1], b[2]) for p, b in zip(parts, base)]


def build_columns(header_rows):
    """
    Turn header rows into column descriptions.

    Header rows are stacked on top of each other ("Consolidated / 2025 /
    $ million").  Each piece joins the column whose centre it is nearest to, so a
    two-line heading ("Freehold land" over "and buildings") stays together even
    when the lines have different numbers of pieces.  The columns are those of the
    header row with the most pieces.
    """
    rows = [r for r in header_rows if len(r) >= 2]
    if not rows:
        return None
    return positioned_columns(header_rows, max(rows, key=len))


def column_base(column, index, period_end):
    """
    The key for a column before duplicates are resolved.

    Preferred: the period end date ("2025-08-31").  If the header only gives a
    year, the day and month of the document's period end are used.  Columns
    with text headings ("Plant and equipment") use that text.
    """
    if column["period_end"]:
        return column["period_end"].isoformat()
    if column["year"] and period_end:
        try:
            derived = period_end.replace(year=column["year"])
            column["period_end"] = derived
            return derived.isoformat()
        except ValueError:
            return str(column["year"])
    if column["year"]:
        return str(column["year"])
    return re.sub(r"\W+", "_", column["text"].lower()).strip("_") or f"col{index + 1}"


def column_qualifier(column):
    """
    What distinguishes two columns for the same date: 'consolidated' vs 'llp'.
    """
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", column["text"])
    text = STATUS.sub(" ", text)
    text = UNITS.sub(" ", text).replace(".", "")  # OCR reads "LLP" as "L.Lp"
    return re.sub(r"\W+", "_", text.lower()).strip("_")
