"""
Cross-checking totals against the rows above them.

A figure that does not equal the sum of its rows usually means an OCR digit
error, so it is reported as a warning for a human to check against the PDF.
"""

import re

from extract_data.parsing.figures import same

STRONG_TOTAL = re.compile(r"^total\b", re.I)
WEAK_TOTAL = re.compile(
    r"^(net\b|gross (profit|surplus|loss)|operating (profit|loss|surplus|deficit)|"
    r"(profit|loss|income|surplus|deficit)\b.*\b(before|for|after)\b|"
    r"comprehensive income|closing balance|balance at|shareholders'? funds|capital employed)", re.I)


def mismatch_warning(table, key, row, value, sums):
    """
    The warning for a total that matches none of the sums of the rows above it.

    `sums` are the sums of the candidate groups; the closest is reported, with the difference,
    and a hint about the likely cause.
    """
    label = row["label"]
    detail, hint = "", "check the PDF: this may be an OCR misread or an error in the filing itself"
    unreadable = [r["label"] for r in table["rows"] if "unreadable_figure" in r.get("flags", [])]
    if unreadable:
        hint = f"a figure could not be read in: {'; '.join(unreadable)}; check the PDF"
    if sums:
        closest = min(sums, key=lambda s: abs(s - value))
        detail = f" add up to {closest:,} (difference {value - closest:+,})"
        if abs(value - closest) <= 2:
            hint = ("check the PDF: a difference this small is often rounding in the accounts, "
                    "but it can also be a misread figure (such as a dash read as '1')")
    return (f"{table['name']} ({key}): '{label or 'subtotal'}' is {value:,} but the rows above"
            f"{detail or ' do not add up to it'}; {hint}.")


class ColumnChecker:
    """
    Walks the rows of one table column keeping the three groups of rows a total may sum
    (see check_column).  Rows are fed in order through `check_row`.
    """

    def __init__(self, table, key, warnings):
        self.table, self.key, self.warnings = table, key, warnings
        self.in_section, self.fresh, self.block, self.totals = [], [], [], []
        self.section = None

    def figure(self, row):
        """The row's figure in this column; a cell the page left blank counts as 0."""
        value = row["values"].get(self.key)
        return 0 if value is None and self.key in row.get("_blank", ()) else value

    def matches(self, value, group):
        """Does `value` equal the sum of the rows in `group`?"""
        if not group:
            return False
        figures = [self.figure(r) for r in group]
        known = sum(f for f in figures if f is not None)
        missing = [r for r, f in zip(group, figures) if f is None]
        if not missing:
            return same(known, value)
        if len(missing) == 1 and same(known, value):
            missing[0]["values"][self.key] = 0  # assume the dropped cell was nil
            missing[0].setdefault("flags", []).append(f"nil_assumed:{self.key}")
            return True
        return False

    @staticmethod
    def replace(group, members, row):
        """`group` with the rows in `members` replaced by `row`."""
        return [r for r in group if not any(r is m for m in members)] + [row]

    def groups(self):
        """The candidate groups of rows a total may equal."""
        first = self.table["rows"][0]
        # Tax reconciliations start from a base figure ("Surplus before tax") that is not part of the sum.
        after_first = [r for r in self.block if r is not first] if first in self.block else []
        return (self.in_section, self.fresh, self.block, after_first)

    def accept_total(self, row, members, subtotal, value):
        """A verified total replaces the rows it summed, so a later total can build on it."""
        self.in_section = self.replace(self.in_section, members, row)
        self.block = [row] if members is self.block else self.replace(self.block, members, row)
        if subtotal:
            self.fresh = self.replace(self.fresh, members, row)
        else:
            row["kind"] = "total"
            self.totals.append(value)
            self.fresh = []

    def find_members(self, value, groups):
        """The group of rows `value` is the sum of, [] if it equals an earlier total, else None."""
        members = next((g for g in groups if self.matches(value, g)), None)
        if members is None and any(same(value, t) for t in self.totals):
            return []
        return members

    def worth_reporting(self, subtotal):
        """Is there enough above a total that does not add up for the mismatch to mean something?"""
        if subtotal:
            return len(self.in_section) >= 2
        return bool(self.in_section or self.fresh or self.block or self.totals)

    def check_row(self, row):
        if row["section"] != self.section:
            self.section, self.in_section = row["section"], []
        value, label = self.figure(row), row["label"]
        subtotal = row["kind"] == "subtotal"
        strong = subtotal or bool(STRONG_TOTAL.match(label))

        if value is not None and (strong or WEAK_TOTAL.match(label)):
            groups = self.groups()
            members = self.find_members(value, groups)
            if members is not None:
                self.accept_total(row, members, subtotal, value)
                return
            if strong and self.worth_reporting(subtotal):
                sums = [sum(self.figure(r) or 0 for r in g) for g in groups if g]
                self.warnings.append(mismatch_warning(self.table, self.key, row, value, sums))
                return
        self.in_section.append(row)
        self.fresh.append(row)
        self.block.append(row)


def check_column(table, key, warnings):
    """
    Cross-check the totals of one column and mark which rows are totals.

    A row is treated as a total if its label starts with "Total", reads like
    a total ("Net assets", "Income for the period") or has no label at all.
    It is verified if its figure equals the sum of one of three groups of rows:
      * the section it is in (rows since the section heading),
      * the rows since the last verified total, or
      * the running list of all rows so far.
    When a total is verified, the rows it summed are replaced in these groups
    by the total itself, so a later total can build on it.  A total can also
    equal an earlier total (e.g. "Total liabilities and equity" = "Total assets").
    A "Total ..." row, or a subtotal in a section with several rows, that
    matches none of these is reported, as that usually means an OCR digit
    error.  Rows that merely look like totals but do not add up are treated as
    ordinary rows and not reported.
    A single missing figure (a "-" the OCR dropped) is assumed to be nil if
    that is what makes the total add up.
    """
    checker = ColumnChecker(table, key, warnings)
    for row in table["rows"]:
        checker.check_row(row)
