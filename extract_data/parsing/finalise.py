"""
Finishing a scanned table: column keys, figures placed under their columns.

Turns the raw output of tables.extract_tables into the final form, where
every row has one value per column key.  Horizontal positions are used to
place a figure under the right column when neighbouring cells are blank.
"""

from collections import Counter

from extract_data.parsing.columns import column_base, column_qualifier, parse_column
from extract_data.parsing.figures import detect_units
from extract_data.parsing.labels import standard_label
from extract_data.parsing.tables import NOTE_REF


def place_by_position(spans, columns):
    """
    The column index each figure sits under, or None if that is not clear.

    A figure belongs to the column whose header it is nearest to, comparing
    both right edges (numbers are usually right-aligned under their heading)
    and centres.  The answer is only used if the figures land in different
    columns, in left-to-right order.
    """

    def distance(span, column):
        a, b = span
        c1, c2 = column["x"]
        return min(abs(b - c2), abs((a + b) / 2 - (c1 + c2) / 2))

    slots = [min(range(len(columns)), key=lambda i: distance(span, columns[i])) for span in spans]
    return slots if len(set(slots)) == len(slots) and slots == sorted(slots) else None


def merge_value_rows(rows):
    """
    Join a label-only row to the unlabelled row of figures printed under it.

    Two causes look the same after OCR: a row whose own figures were lost,
    followed by a subtotal ("Cash and cash equivalents" / "9,541"), or a label
    and its figures printed on separate lines ("Members' interest at 1 April" /
    "361,003  (1,499,816) ..."). If the figures equal the sum of the rows
    above them, they are a subtotal; otherwise they belong to the label.
    """
    result, i = [], 0
    while i < len(rows):
        row = rows[i]
        following = rows[i + 1] if i + 1 < len(rows) else None
        if following and is_label_without_figures(row, following) and not is_subtotal_of(following, row, result):
            take_figures_from_next_line(row, following)
            result.append(row)
            i += 2
        else:
            result.append(row)
            i += 1
    return result


def is_label_without_figures(row, following):
    """A label whose own figures were not read, followed by a row of figures with no label."""
    return ("no_figures_read" in row.get("flags", [])
            and row["kind"] == "line" and following["kind"] == "subtotal")


def is_subtotal_of(following, row, result):
    """Do the figures in `following` equal the sum of the lines above `row` in its section?"""
    earlier = []
    for previous in reversed(result):
        if previous["section"] != row["section"] or previous["kind"] != "line":
            break
        earlier.append(previous)
    return all(value is None or sum((r["values"].get(k) or 0) for r in earlier) == value
               for k, value in following["values"].items())


def take_figures_from_next_line(row, following):
    """The figures printed on the next line belong to this row's label."""
    row["values"] = following["values"]
    row["flags"] = [f for f in row["flags"] if f != "no_figures_read"] + ["values_on_next_line"]
    row["_blank"] = following.get("_blank", [])


def make_columns(padded, period_end):
    """
    Give each column a key: a date where there is one; if two columns share a date
    ("Consolidated" and "LLP"), add what tells them apart.
    """
    bases = [column_base(c, i, period_end) for i, c in enumerate(padded)]
    duplicated = {b for b, n in Counter(bases).items() if n > 1}
    used, columns = set(), []
    for i, (raw, base) in enumerate(zip(padded, bases)):
        key = base
        if base in duplicated:
            dated = raw["period_end"] or raw["year"]  # text-only keys are told apart by position
            key = f"{base}_{(column_qualifier(raw) if dated else '') or i + 1}"
        if key in used:
            key = f"{key}_{i + 1}"
        used.add(key)
        columns.append({"key": key, "label": raw["text"],
                        "period_end": raw["period_end"].isoformat() if raw["period_end"] else None,
                        "status": raw["status"]})
    return columns


def split_note_ref(label, figures, spans, raw_columns):
    """
    Separate a note reference from a row: returns (note, label, figures, spans).

    The reference is either written in the label ("Investments (Note 2)") or is a small first
    figure that sits to the left of the first column ("Tangible assets  3  773,374  773,587").
    """
    match = NOTE_REF.search(label)
    if match:
        return match.group(1), NOTE_REF.sub("", label).strip(), figures, spans
    if (figures and label and raw_columns and isinstance(figures[0], int) and 0 < figures[0] < 100
            and spans[0][1] < raw_columns[0]["x"][0]):
        return str(figures[0]), label, figures[1:], spans[1:]
    return None, label, figures, spans


def align_figures(figures, spans, label, padded, has_columns, flags):
    """
    Put a row's figures under the table's columns: returns (one value per column, blank column indexes).

    Too many figures keep the last ones; too few are placed by position when the table has
    columns and that is clear, else right-aligned.  Each of these is noted in `flags` (changed in place).
    """
    count = len(padded)
    if len(figures) == count:
        return figures, []
    if len(figures) > count:
        flags.append("extra_figures_dropped")
        return figures[-count:], []
    if not figures:
        if label and "no_figures_read" not in flags:
            flags.append("no_figures_read")
        return [None] * count, []
    slots = place_by_position(spans, padded) if has_columns else None
    if slots is None:
        flags.append("partial_alignment")
        return [None] * (count - len(figures)) + figures, []
    aligned = [None] * count
    for slot, value in zip(slots, figures):
        aligned[slot] = value
    flags.append("aligned_by_position")
    return aligned, [i for i in range(count) if i not in slots]  # cells with nothing printed


def finalise_row(row, table, columns, padded, raw_columns):
    """One scanned row in its final form (values keyed by column, note reference split off)."""
    figures, spans, flags = list(row["raw"]), list(row["vx"]), list(row.get("flags", []))
    note, label, figures, spans = split_note_ref(row["label"], figures, spans, raw_columns)
    aligned, blank = align_figures(figures, spans, label, padded, bool(raw_columns), flags)

    entry = {"section": row["section"], "label": label or "Subtotal", "note": note,
             "kind": "line" if label else "subtotal",
             "values": {c["key"]: v for c, v in zip(columns, aligned)},
             "_blank": [columns[i]["key"] for i in blank]}
    if table["kind"] == "statement" and label:
        entry["standard"] = standard_label(label)
    if flags:
        entry["flags"] = flags
    return entry


def finalise_table(table, period_end):
    """
    Turn a scanned table into its final form.

    Gives each column a key, places the figures under their columns (using
    horizontal positions when known, otherwise right-aligning short rows and
    flagging them), splits note references off, and names unlabelled rows
    "Subtotal".  Returns None for tables with no figures (for example a
    contents page).
    """
    if not table["rows"]:
        return None
    raw_columns = table["columns"] or []
    count = len(raw_columns) or max(len(r["raw"]) for r in table["rows"])
    if count == 0:
        return None
    padded = [raw_columns[i] if i < len(raw_columns) else parse_column("") for i in range(count)]
    columns = make_columns(padded, period_end)
    rows = [finalise_row(row, table, columns, padded, raw_columns) for row in table["rows"]]

    currency, multiplier = detect_units(" ".join(c["text"] for c in raw_columns))
    return {"kind": table["kind"], "name": table["name"], "note_number": table["note_number"],
            "page": table["page"], "currency": currency, "unit_multiplier": multiplier,
            "columns": columns, "rows": merge_value_rows(rows)}
