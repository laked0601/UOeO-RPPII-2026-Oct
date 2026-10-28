"""
Flat, SQL-ready version of the extracted data.

extract_document (document.py) returns nested data: statements and note tables,
each with rows, each row with a value per column.  That is easy to read but
awkward to load into a database.  This module turns it into "facts": one row
per figure, with everything needed to identify it on the same row.

    source_file, company_number, ..., table_name, section, label, column_key, value

Loading the CSV into a single table (for example `facts`) needs no joins.
Company and table details repeat on every row; split them into separate
tables later if you want a normalised schema, using these columns as keys:
    company  : company_number
    filing   : source_file
    table    : source_file + table_number
    figure   : source_file + table_number + row_number + column_key

Blank cells are not written: a fact exists only where a figure was read (or a
nil was inferred, which is flagged).
"""

import csv

# The columns of a fact, in output order.
FACT_COLUMNS = [
    "source_file", "filing_type", "filing_date",  # which document
    "company_number", "period_end",  # which company and period
    "currency", "unit_multiplier",  # what the figures are in
    "table_number", "table_kind", "table_name", "table_note_number", "page",  # which table
    "row_number", "section", "label", "row_note_ref", "standard_label", "row_kind",  # which row
    "column_key", "column_label", "column_period_end", "column_status",  # which column
    "value",  # the figure itself
    "flags",  # anything to double-check
]


def facts_flags(row_flags, column_key):
    """
    Flags that apply to one figure, as a ';'-separated string.

    Row flags are either about the whole row ("values_on_next_line") or about
    one column ("nil_assumed:2025-03-31").  A column flag is kept only for its
    own column, and written without the column ("nil_assumed").
    """
    kept = []
    for flag in row_flags or []:
        name, _, target = flag.partition(":")
        if not target or target == column_key:
            kept.append(name)
    return ";".join(kept)


def to_facts(result):
    """
    One dict per figure in an extract_document result.

    Statements come first, then note tables, in the order they appear in the
    result.  `table_number` counts them from 1 and, with `source_file`,
    identifies a table; `row_number` counts rows within a table from 1.
    """
    document = document_fields(result)
    facts = []
    tables = result.get("statements", []) + result.get("note_tables", [])
    for table_number, table in enumerate(tables, start=1):
        columns = {c["key"]: c for c in table["columns"]}

        for row_number, row in enumerate(table["rows"], start=1):

            for key, value in row["values"].items():
                if value is not None:  # a blank cell: no figure to record
                    where = {"table_number": table_number, "row_number": row_number}
                    facts.append({**document, **where, **figure_fields(table, row, columns[key], key, value)})

    return facts


def document_fields(result):
    """
    The fields every fact of a filing shares: which document, company, period and units.
    """
    company = result.get("company", {})
    filing = result.get("filing") or {}

    return {
        "source_file": result.get("source_file"),
        "filing_type": filing.get("type"),
        "filing_date": filing.get("date"),
        "company_number": company.get("registration_number"),
        "period_end": company.get("period_end"),
        "currency": company.get("currency"),
        "unit_multiplier": company.get("unit_multiplier"),
    }


def figure_fields(table, row, column, key, value):
    """
    The fields of one figure: its table, row and column details, the value and any flags.
    """
    return {
        "table_kind": table["kind"],
        "table_name": table["name"],
        "table_note_number": table["note_number"],
        "page": table["page"],
        "section": row["section"] or None,
        "label": row["label"],
        "row_note_ref": row["note"],
        "standard_label": row.get("standard"),
        "row_kind": row["kind"],
        "column_key": key,
        "column_label": column["label"],
        "column_period_end": column["period_end"],
        "column_status": column["status"],
        "value": value,
        "flags": facts_flags(row.get("flags"), key) or None,
    }


def write_facts(facts, out_dir, stem):
    """
    Save facts as <stem>.facts.csv in `out_dir`; returns the path.

    The CSV is UTF-8 with a header row; empty cells are empty (SQL NULL when
    imported with an "empty string as NULL" option).
    """
    csv_path = out_dir / f"{stem}.facts.csv"

    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FACT_COLUMNS)
        writer.writeheader()
        writer.writerows(facts)

    return csv_path
