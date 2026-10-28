"""
Finding the statements and note tables on each page, and their columns.

`extract_tables` scans the rows of every page top to bottom: headings such as
"BALANCE SHEET" start a statement, numbered headings start a note table, and
the header rows (years, "Unaudited", "Group") above the figures become columns (see columns.py).
The result is still "raw": figures are not yet placed under their columns
(see finalise.py).
"""

import re

from extract_data.parsing.columns import build_columns, header_from
from extract_data.parsing.figures import find_dates, is_year_row

STATEMENT_HEADING = re.compile(
    r"^(?:(?:consolidated|company|group|llp|parent company|abbreviated|filleted|unaudited|audited|summary|and)\s+)*"
    r"(?:balance sheets?|statements? of financial position|statements? of comprehensive income|"
    r"statements? of income|income statements?|profit and loss accounts?|income and expenditure accounts?|"
    r"statements? of profit or loss(?: and other comprehensive income)?|"
    r"statements? of cash flows?|cash flow statements?|statements? of financial activities|"
    r"statements? of changes in (?:shareholders'? |members'? )?(?:equity|interests?|reserves)|"
    r"statements? of members'? interests?|statements? of retained earnings)"
    r"\s*(?:\(continued\))?(?:\s+(?:as at|at|for the)\b.*)?$", re.I)

NUMBERED_TITLE = re.compile(r"^(\d{1,2})(?:\.\d+)?\s*[.)]?\s*([A-Za-z].*)$")
DATE_HINT = re.compile(r"^(as at|for the (?:financial )?(?:year|period)|(?:year|period) ended)\b", re.I)
NOTE_WORDS = ("note", "notes")
JUNK_LABEL = re.compile(r"^(notes?|[-–\s\d.]*)$", re.I)
NOTE_REF = re.compile(r"\s*\(?\bnotes?\s+(\d+(?:\s*[,&-]\s*\d+)*)\)?", re.I)


def is_prose(label):
    """
    Long sentences and lines ending in punctuation are text, not headings.
    """
    return len(label) > 80 or label.endswith((".", ":"))


def is_note_title(label, rows, index):
    """
    Decide whether a value-less row starts a new note table.

    Yes if it is numbered ("3  Tangible fixed assets"), or if a column header
    of years comes next (OCR sometimes loses the number), skipping at most
    three lines of explanatory text.
    """
    if is_prose(label) or JUNK_LABEL.match(label):
        return False

    if NUMBERED_TITLE.match(label):
        return True

    for row in rows[index:index + 3]:
        if not row["label"] and is_year_row(row):
            return True

        if row["values"] or not is_prose(row["label"]):
            return False

    return False


def split_title(label, frags):
    """
    The note number (or None) and the title of a heading, and whether the number was a piece of text
    of its own ("11  DEBTORS") rather than part of the title's text ("11 DEBTORS").
    """
    if len(frags) > 1 and re.fullmatch(r"\d{1,2}\.?", frags[0]):
        return frags[0].rstrip("."), frags[1], True

    m = NUMBERED_TITLE.match(label)

    return (m.group(1), m.group(2), False) if m else (None, label, False)


def new_table(kind, name, page, note_number=None):
    """An empty table, filled in by extract_tables."""
    return {"kind": kind, "name": name, "page": page, "note_number": note_number,
            "header_rows": [], "columns": None, "rows": [], "date_hint": None}


# Table scan


def clean_statement_name(text):
    """"
    BALANCE SHEET (continued)" -> "Balance sheet"; LLP and PLC keep their capitals.
    """
    name = re.sub(r"\s*\(continued\)", "", text, flags=re.I).strip().capitalize()

    return re.sub(r"\b(Llp|Plc)\b", lambda m: m.group(1).upper(), name)


def looks_like_header_pieces(frags):
    """
    Several short text pieces (not garbled figures) that could be column headings.
    """
    return (2 <= len(frags) <= 8 and not frags[0].endswith(":")
            and all(len(f) <= 50 for f in frags)
            and not any(re.fullmatch(r"[\s\d.,()-]+", f) for f in frags))


def is_short_heading_text(row):
    """
    A line of one short piece of text with no figures ("Plant and"), which could start a column heading.
    """
    label = row["label"]

    return (not row["values"] and len(row["frags"]) == 1 and len(label) <= 30 and not label.endswith(":")
            and not DATE_HINT.match(label) and not JUNK_LABEL.match(label))


def is_wide_header_line(row):
    """
    A line of two or more short pieces of text with no figures ("machinery  Motor").
    """
    return not row["values"] and len(row["frags"]) >= 2 and all(len(f) <= 50 for f in row["frags"])


class TableScanner:
    """
    Reads the rows of one document page by page and collects its tables.

    Things remembered while scanning:
      pending       header rows seen before their heading, as on Shell's pages
                    where "Unaudited / December 31, 2025" sits above "BALANCE SHEET"
      page_columns  so a second statement on the same page, which has no header
                    of its own, reuses the first one's columns
      current       the table rows are being added to
    Each row is offered to the rules in `RULES` in order; the first rule that recognises it
    (returns True) consumes it.  Rows no rule consumes are rows of figures, added by `add_figures`.
    """

    def __init__(self):
        self.tables = []
        self.rules = [self.statement_heading, self.note_title, self.title_with_years, self.year_header,
                      self.header_pieces, self.wrapped_header_start, self.date_hint,
                      self.dropped_figures, self.text_without_figures]

    # Pages
    def scan_page(self, page_no, rows):
        """
        Scan one page top to bottom.
        """
        self.page_no, self.rows = page_no, rows
        self.current = None
        self.pending = []
        self.page_columns = None
        self.section = ""
        self.last_heading = None
        for index, row in enumerate(rows):
            self.row = row
            self.following = rows[index + 1] if index + 1 < len(rows) else None
            self.index = index
            if not any(rule(row) for rule in self.rules):
                self.add_figures(row)

    @property
    def has_rows(self):
        return bool(self.current and self.current["rows"])

    def start_table(self, kind, name, note_number=None):
        """
        Open a new table on this page and make it current.
        """
        self.current = new_table(kind, name, self.page_no, note_number)
        self.tables.append(self.current)
        return self.current

    # Rules
    def statement_heading(self, row):
        """
        A statement heading ("BALANCE SHEET"), possibly followed on the same line by units
        ("S million  $ million") that belong to its header.
        """
        frags = row["frags"]
        if row["values"] or not frags or not STATEMENT_HEADING.match(frags[0]):
            return False
        table = self.start_table("statement", clean_statement_name(frags[0]))
        table["header_rows"], self.pending = self.pending, []
        if len(frags) >= 3:
            table["header_rows"].append(header_from(frags[1:], row["fx"][1:]))
        self.section = ""
        return True

    def note_title(self, row):
        """
        A note title ("3  Tangible fixed assets") starts a new note table.  Checked before the
        column header rules because "2  Employees" is also two short pieces of text.
        """
        label, frags = row["label"], row["frags"]

        if not (not row["values"] and label and not DATE_HINT.match(label)
                and (NUMBERED_TITLE.match(label) or len(frags) == 1)
                and is_note_title(label, self.rows, self.index + 1)):
            return False
        number, title, separate = split_title(label, frags)
        table = self.start_table("note", title, number)

        if separate and len(frags) >= 3:
            # "11  DEBTORS  Group  Company": the pieces after the title are column headings.
            table["header_rows"].append(header_from(frags[2:], row["fx"][2:]))
        self.pending, self.section = [], ""
        self.last_heading = label
        return True

    def title_with_years(self, row):
        """
        A title and its year headings on one line ("2  Employees  2026  2025").
        """
        label, frags = row["label"], row["frags"]
        if not (label and label.lower() not in NOTE_WORDS and is_year_row(row)):
            return False

        number, title, _ = split_title(label, frags)
        table = self.start_table("note", title, number)
        table["header_rows"] = [header_from(row["tokens"], row["vx"])]
        self.pending, self.section, self.last_heading = [], "", label

        return True

    def year_header(self, row):
        """
        A row of years ("2025  2024", or "Notes  2025  2024") is a column header.
        """
        label = row["label"]
        if not (is_year_row(row) and (not label or label.lower() in NOTE_WORDS)):
            return False

        target = self.pending if (self.has_rows or self.current is None) else self.current["header_rows"]
        target.append(header_from(row["tokens"], row["vx"]))
        return True

    def header_pieces(self, row):
        """
        Several short text pieces before any figures: more column header ("Unaudited  Audited",
        "Freehold land  Plant and  Total").
        Lines such as "Registered number:  12345" are not.
        """
        if row["values"] or self.has_rows or not looks_like_header_pieces(row["frags"]):
            return False

        (self.current["header_rows"] if self.current else self.pending).append(
            header_from(row["frags"], row["fx"]))

        return True

    def wrapped_header_start(self, row):
        """
        The first line of a wrapped column heading can be a single piece of text ("Plant and"
        above "machinery  Motor"): it is header if more header follows.
        """
        following = self.following

        if not (self.current and not self.has_rows and is_short_heading_text(row)
                and following and is_wide_header_line(following)):
            return False
        self.current["header_rows"].append(header_from(row["frags"], row["fx"]))
        return True

    def date_hint(self, row):
        """"AS AT 31 AUGUST 2025" gives the statement date."""
        if row["values"] or not DATE_HINT.match(row["label"]):
            return False
        if self.current and not self.current["date_hint"]:
            found = find_dates(row["label"])
            self.current["date_hint"] = found[-1] if found else None
        return True

    def dropped_figures(self, row):
        """
        A label with no figures, followed by a row of figures with no label ("Cash and cash
        equivalents" / "9,541  7,346"): either the OCR dropped this row's own figures (usually a
        "-" for nil), or the figures were printed on the next line.  Keep the row;
        finalise_table decides which it was.
        """
        following = self.following
        if not (not row["values"] and row["label"] and self.current and following
                and not following["label"] and len(following["values"]) >= 2
                and not is_year_row(following)):
            return False
        self.current["rows"].append({"section": self.section, "label": row["label"], "raw": [], "tokens": [],
                                     "vx": [], "flags": ["no_figures_read"]})
        return True

    def text_without_figures(self, row):
        """Other value-less text: a section heading ("Current assets"), or sentences."""
        if row["values"]:
            return False
        label = row["label"]
        if not label or JUNK_LABEL.match(label):
            return True
        # Inside a table, a short line ending in a colon names a group of rows
        # ("Fees for the audit of subsidiary undertakings:").
        if not (label.endswith(":") and self.has_rows and len(label) <= 100) and is_prose(label):
            return True
        self.section = self.last_heading = label
        return True

    # Figures
    def table_for_figures(self, row):
        """
        The table a row of figures belongs to, started if need be; None if the row is not a table row.
        """
        if self.current is not None:
            return self.current
        # Without a title, a table is only started by a labelled row of at least two
        # figures; page numbers, "Registered number: 05421996" and stray numbers are not tables.
        if len(row["values"]) < 2 or not row["label"] or JUNK_LABEL.match(row["label"]):
            return None
        previous = self.tables[-1] if self.tables else None
        if previous and previous["page"] == self.page_no - 1 and previous["rows"]:
            # continues the previous page's table
            self.current, self.section = previous, previous["rows"][-1]["section"]
        else:
            table = self.start_table("note", self.last_heading or "Untitled")
            table["header_rows"], self.pending = self.pending, []
        return self.current

    def set_columns(self, table):
        """
        Give the table its columns the first time a row of figures is reached.
        """
        if table["columns"] is not None:
            return
        columns = build_columns(table["header_rows"]) if table["header_rows"] else None
        if not columns and table["kind"] == "statement":
            columns = self.page_columns  # reuse this page's earlier header
        table["columns"] = columns or []
        self.page_columns = columns or self.page_columns

    def is_page_number(self, row, table):
        """
        A lone unlabelled number is a page number (printed pages need not match the PDF's),
        not a subtotal, unless the table already has rows to sum and the number is not tiny.
        """
        values = row["values"]
        return (not row["label"] and len(values) == 1 and (
                values[0] == self.page_no or len(table["columns"]) > 1
                or len(table["rows"]) < 2 or (isinstance(values[0], int) and abs(values[0]) < 100)))

    def add_figures(self, row):
        """
        A row with figures: add it to the table it belongs to.
        """
        table = self.table_for_figures(row)
        if table is None:
            return
        self.set_columns(table)
        if self.is_page_number(row, table):
            return
        entry = {"section": self.section, "label": row["label"], "raw": row["values"],
                 "tokens": row["tokens"], "vx": row["vx"]}
        if None in row["values"]:  # a printed figure the OCR garbled
            entry["flags"] = ["unreadable_figure"]
        table["rows"].append(entry)


def extract_tables(pages_rows):
    """
    Scan every page and collect statements and note tables (still unaligned).

    A table with no title at the top of a page continues the previous page's table.
    """
    scanner = TableScanner()

    for page_no, rows in enumerate(pages_rows, start=1):
        # A contents page lists headings and page numbers; it holds no accounts' data.
        if any(r["label"].strip().lower() == "contents" for r in rows):
            continue

        scanner.scan_page(page_no, rows)

    return scanner.tables
