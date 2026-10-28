"""
Generic extraction of Companies House accounts, for any layout.

These modules read whatever tables are on the page, so they work for any kind of accounts
(small company, full accounts, interim accounts, PLCs, LLPs, group accounts, other currencies
and units, ...).

The pipeline, and the module that does each step:

    rows.py      every OCR row is split into a label and its trailing figures
                 (figures.py repairs the numbers, dates and currencies)
    tables.py    each page is scanned top to bottom for statements ("BALANCE
                 SHEET") and note tables ("3  Tangible fixed assets"); header
                 rows become columns
    finalise.py  each figure is placed under its column (using horizontal
                 positions when a row has blank cells) and gets a column key;
                 labels.py gives rows a standard name
    totals.py    totals are cross-checked against the rows above them, which
                 finds OCR digit errors and recognises which rows are totals
    company.py   registration number, period end and approval date are read from
                 the text of the whole document

This module ties the steps together in `extract_document`.

The result is plain JSON-friendly data: every figure is stored with its
statement, section, label and column, which maps directly onto SQL rows.
"""

from collections import Counter

from extract_data.parsing.company import extract_company
from extract_data.parsing.finalise import finalise_table
from extract_data.parsing.rows import read_rows, to_lines
from extract_data.parsing.tables import extract_tables
from extract_data.parsing.totals import check_column


def most_common_currency(tables, pages_lines):
    """
    The (currency, unit multiplier, assumed) most tables agree on.

    When no table states a currency (the OCR often drops the pound sign) the wording is checked
    for sterling; failing that, pounds in whole units are assumed, as these are Companies House
    filings, and `assumed` is True so the log can say so.
    """
    currencies = Counter((t["currency"], t["unit_multiplier"]) for t in tables if t["currency"])
    if currencies:
        return (*currencies.most_common(1)[0][0], False)
    text = " ".join(" ".join(lines) for lines in pages_lines).lower()
    return "GBP", 1, not ("sterling" in text or "£" in text)


def check_tables(tables, warnings, flagged_pages):
    """
    Verify the totals of every column of every table; report problems in `warnings`.

    Page numbers of tables that raised a warning are added to `flagged_pages` (if it is a set).
    """
    for table in tables:
        before = len(warnings)
        for column in table["columns"]:
            check_column(table, column["key"], warnings)
        if flagged_pages is not None and len(warnings) > before:
            flagged_pages.add(table["page"])
        for row in table["rows"]:
            row.pop("_blank", None)  # working data, not part of the output
    if not any(t["kind"] == "statement" for t in tables):
        warnings.append("no financial statements found")


def extract_document(pages, source_file="", flagged_pages=None):
    """
    Extract everything from one filing.

    `pages` is a list of pages; each page is a list of rows, each a list of OCR fragments
    (x_left, text, x_right).  Their positions let figures be placed under the right column.
    If `flagged_pages` is a set, the page numbers (from 1) of tables whose totals did not add
    up are added to it: those are the pages worth reading again at a higher resolution.
    Returns a JSON-friendly dict:
      company      registration number, period end, approval date, ...
      statements   balance sheet, income statement, ... as rows x columns
      note_tables  tables from the notes
      warnings     anything that needs a human check
    """
    warnings = []
    pages_lines = [to_lines(page) for page in pages]

    # Steps 1-2: read the rows of every page, then find the tables and their headers.
    scanned = extract_tables([read_rows(page) for page in pages])

    # The company details come first because the period end is needed to name year-only columns.
    company, filing, period_end = extract_company(pages_lines, scanned, source_file, warnings)

    # Step 3: place the figures, then step 4: verify the totals column by column.
    tables = [t for t in (finalise_table(s, period_end) for s in scanned) if t]
    check_tables(tables, warnings, flagged_pages)
    company["currency"], company["unit_multiplier"], company["currency_assumed"] = \
        most_common_currency(tables, pages_lines)

    result = {"source_file": source_file}
    if filing:
        result["filing"] = filing
    result["company"] = company

    result["statements"] = [t for t in tables if t["kind"] == "statement"]
    result["note_tables"] = [t for t in tables if t["kind"] == "note"]
    result["warnings"] = warnings
    return result
