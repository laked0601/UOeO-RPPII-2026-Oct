"""
The standardised view: every filing in the same fixed JSON headings.

document.py reads whatever tables a filing contains, so two filings give
differently shaped output (different row labels, different statements).  This
module maps those rows onto one fixed set of headings, so any filing can be
compared with any other or loaded into the same SQL columns:

    standardised.entities.<entity>.periods.<period end>.<group>.<heading>

* Groups and headings are always the same (see SCHEMA).  A heading the filing
  does not contain is null; it is never missing and never invented.
* Entities: "company" is the reporting company or LLP; "group" is the
  consolidated accounts and exists only for filings that include them.
* Periods: one block per period end date found in the statements, newest first,
  with the audit status ("Audited"/"Unaudited") where the filing gives it.
* Values keep the sign printed in the accounts (creditors and costs are
  negative where the accounts show them in brackets; a loss is negative).
  They are in the units given by `currency` and `unit_multiplier`.
* Figures come from the statements (via the standard label of each row) and,
  for depreciation and employees, from the notes.
* Anything not mapped is reported, not dropped: `unmapped` lists the statement
  rows with no heading, `conflicts` lists a heading found twice with different
  values, and `inferred` lists figures that were not printed but taken as nil
  because that is what makes the statement add up.
"""

import re
from datetime import timedelta

from extract_data.parsing.figures import find_dates
from extract_data.parsing.labels import STANDARD_LABELS

SCHEMA_VERSION = 1

# The fixed headings.  Order here is the order in the output.
SCHEMA = {
    "assets": [
        "intangible_assets", "tangible_assets", "investments", "fixed_assets",
        "stocks", "debtors", "cash", "current_assets", "total_assets",
    ],
    "creditors": [
        "creditors_within_one_year", "creditors_after_one_year", "provisions", "deferred_tax", "total_liabilities",
    ],
    "net_assets": [
        "net_current_assets", "total_assets_less_current_liabilities", "net_assets",
    ],
    "capital_and_reserves": [
        "share_capital", "share_premium", "revaluation_reserve", "other_reserves", "retained_earnings",
        "members_capital", "loans_due_to_members", "non_controlling_interests",
        "total_equity", "total_equity_and_liabilities",
    ],
    "income": [
        "turnover", "other_operating_income", "dividend_income", "interest_receivable",
    ],
    "costs": [
        "cost_of_sales", "administrative_expenses", "interest_payable",
    ],
    "profit_and_loss": [  # a loss is a negative figure
        "gross_profit", "operating_profit", "profit_before_tax", "tax", "profit_for_period",
        "comprehensive_income", "dividends_paid",
    ],
    "depreciation": [  # from the tangible fixed assets note
        "tangible_cost", "depreciation_charge", "accumulated_depreciation", "net_book_value",
    ],
    "other": [
        "average_employees",
    ],
}
FIELD_GROUP = {field: group for group, fields in SCHEMA.items() for field in fields}

# Every standard label that document.py can give a row must have a heading here.
MISSING_HEADINGS = set(STANDARD_LABELS) - set(FIELD_GROUP)
assert not MISSING_HEADINGS, f"standard labels without a heading: {MISSING_HEADINGS}"

# An unlabelled subtotal is named by the section it closes ("Current assets" -> 728,736).
SECTION_SUBTOTALS = {"fixed assets": "fixed_assets", "non-current assets": "fixed_assets",
                     "non current assets": "fixed_assets", "current assets": "current_assets"}

# A row whose label only means something inside its section: (section, label, heading).
SECTION_RULES = [
    (re.compile(r"members", re.I), re.compile(r"^other amounts$", re.I), "loans_due_to_members"),
]


def entity_of(text):
    """
    'group' for consolidated accounts, 'company' for the company/LLP itself, else None.
    """
    text = (text or "").lower()
    if "consolidated" in text or re.search(r"\bgroup\b", text):
        return "group"

    if re.search(r"\b(llp|company|parent)\b", text):
        return "company"

    return None


def blank_period():
    """
    A period with every heading present and null.
    """
    return {"status": None, **{group: {field: None for field in fields} for group, fields in SCHEMA.items()}}


def note_section(section):
    """
    The heading a section of the tangible assets note feeds: its cost, its depreciation or its net book value.
    """
    section = section.lower()

    if section.startswith(("cost", "valuation")):
        return "tangible_cost"

    if section.startswith(("depreciation", "accumulated depreciation")):
        return "accumulated_depreciation"

    if section.startswith(("net book", "carrying")):
        return "net_book_value"

    return None


def value_column(table):
    """
    The key of the column holding totals in a note table (the 'Total' column, else the last).
    """
    for column in table["columns"]:
        if column["key"] == "total" or column["label"].lower().startswith("total"):
            return column["key"]

    return table["columns"][-1]["key"] if table["columns"] else None


def statement_heading(row):
    """
    The standard heading of a statement row, or None: its own label, else the section it closes.
    """
    field = row.get("standard")

    if not field and row["kind"] == "subtotal":
        field = SECTION_SUBTOTALS.get(row["section"].lower())

    if not field:
        field = next((f for s, l, f in SECTION_RULES if s.search(row["section"]) and l.search(row["label"])), None)

    return field


def employees_row(table):
    """
    The row of an employees note that holds the headcount: 'Total', else 'Average', else the only row.
    """
    rows = table["rows"]

    return (next((r for r in rows if r["label"].lower().startswith("total")), None)
            or next((r for r in rows if r["label"].lower().startswith("average")), None)
            or (rows[0] if len(rows) == 1 else None))


def unique_by_label(items):
    """
    Drop repeats of the same statement and label (a label can appear in several columns or periods).
    """
    seen, unique = set(), []

    for item in items:
        marker = (item["statement"], item["label"])

        if marker not in seen:
            seen.add(marker)
            unique.append(item)

    return unique


class Standardiser:
    """
    Collects the figures of one filing under the fixed headings (see standardise).
    """

    def __init__(self, result):
        self.company = result.get("company", {})
        self.statements = result.get("statements", [])
        self.notes = result.get("note_tables", [])
        self.period_end = self.company.get("period_end")
        has_group = any(entity_of(t["name"]) == "group" for t in self.statements)
        self.note_entity = "group" if has_group else "company"
        self.entities = {}
        self.unmapped, self.conflicts, self.inferred = [], [], []

    def put(self, entity, iso, field, value, source, status=None, create=True):
        """
        Record one figure, keeping the first value if a heading turns up twice.
        """
        periods = self.entities.setdefault(entity, {})

        if iso not in periods:
            if not create:
                return

            periods[iso] = blank_period()
        block = periods[iso]

        if status and not block["status"]:
            block["status"] = status
        group = FIELD_GROUP[field]

        if block[group][field] is None:
            block[group][field] = value

        elif block[group][field] != value:
            self.conflicts.append({"entity": entity, "period_end": iso, "heading": f"{group}.{field}",
                                   "kept": block[group][field], "ignored": value, "source": source})

    # Statements: each row's standard label names its heading
    def add_statement(self, table):
        if "cash flow" in table["name"].lower():
            return  # its adjustments ("Taxation", "Interest receivable") are not the results

        table_entity = entity_of(table["name"]) or "company"
        # One table can hold both: "Group  2025  2024  Company  2025  2024".
        periods = [(c["key"], c["period_end"], c["status"], entity_of(c["label"]) or table_entity)
                   for c in table["columns"] if c["period_end"]]

        if not periods:
            return  # e.g. a statement of changes in members' interests

        for row in table["rows"]:
            if all(v is None for v in row["values"].values()):
                continue
            field = statement_heading(row)

            if field:
                self.add_statement_row(table, row, field, periods)

            elif row["kind"] != "subtotal":
                self.unmapped.append({"statement": table["name"], "section": row["section"], "label": row["label"]})

    def add_statement_row(self, table, row, field, periods):
        """Record a mapped row's figure for every period column."""
        for key, iso, status, entity in periods:
            value = row["values"].get(key)
            if value is None:
                continue

            self.put(entity, iso, field, value, f"{table['name']} / {row['label']}", status)

            if f"nil_assumed:{key}" in row.get("flags", []):  # a dash the OCR dropped, taken as nil
                self.inferred.append({"entity": entity, "period_end": iso,
                                      "heading": f"{FIELD_GROUP[field]}.{field}", "reason": "nil_assumed"})

    # Notes: depreciation and employees
    def add_tangible_note(self, table):
        key = value_column(table)

        for row in table["rows"]:
            field, value = note_section(row["section"]), row["values"].get(key)
            if field is None or value is None:
                continue

            source = f"{table['name']} / {row['label']}"

            if field == "accumulated_depreciation" and re.search(r"charge|for the (year|period)", row["label"], re.I):
                if self.period_end:
                    self.put(self.note_entity, self.period_end, "depreciation_charge", value, source)
                continue

            # "At 1 May 2025" is the end of the previous period; a row can name two dates.
            for d in find_dates(row["label"]):
                iso = (d - timedelta(days=1) if d.day == 1 else d).isoformat()
                self.put(self.note_entity, iso, field, value, source, create=(iso == self.period_end))

    def add_employees_note(self, table):
        chosen = employees_row(table)
        for column in table["columns"]:
            value = chosen["values"].get(column["key"]) if chosen else None

            if column["period_end"] and value is not None:
                self.put(self.note_entity, column["period_end"], "average_employees", value,
                         f"{table['name']} / {chosen['label']}", create=True)

    def add_note(self, table):
        name = table["name"].lower()

        if re.search(r"\btangible\b", name):
            self.add_tangible_note(table)

        elif "employee" in name:
            self.add_employees_note(table)

    def result(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "currency": self.company.get("currency"),
            "unit_multiplier": self.company.get("unit_multiplier"),
            "entities": {name: {"periods": {iso: self.entities[name][iso]
                                            for iso in sorted(self.entities[name], reverse=True)}}
                         for name in ("group", "company") if name in self.entities},
            "inferred": self.inferred,
            "unmapped": unique_by_label(self.unmapped),
            "conflicts": self.conflicts,
        }


def standardise(result):
    """
    Build the standardised view of an extract_document result.

    Returns a dict with `entities` (see the module docstring), `unmapped` and
    `conflicts`, plus the currency and unit the figures are in.
    """
    standardiser = Standardiser(result)

    for table in standardiser.statements:
        standardiser.add_statement(table)

    for table in standardiser.notes:
        standardiser.add_note(table)

    return standardiser.result()
