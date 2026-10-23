"""
Parse the data from the input file and return a list of dictionaries.

Input: OCR results from the PDF file
Output: List of dictionaries, each representing a row of data with keys as column names and values as the corresponding data.

1. Split lines
2. pages are located by their content
3. table rows are read from the relevant fields
4. Totals are cross-checked against each other.
"""

import re
from difflib import SequenceMatcher

number_patten = re.compile(r"^\(?-?[\d.,]+\)?$")


def parse_number(text):
    """
    Parse a number from text
    """
    text = text.strip()
    # Check if the number is negative (starts with '(' or '-')
    negative = text.startswith(("(", "-"))
    # Remove parentheses and minus sign for parsing
    strip_text = text.strip("()-")

    if re.fullmatch(r"\d{1,3}([.,]\d{3})+|\d+", strip_text):
        value = int(re.sub(r"[.,]", "", strip_text))
        return -value if negative else value  # Return the parsed integer value
    else:
        return None  # Return None if the text is not a valid number


def build_rows(lines):
    """
    Split each line into {label, value} pairs
    """

    rows = []

    for line in lines:
        fragments = [f for f in line.split("  ") if f.strip()]

        values = []

        # Get numbers from the end of the line
        while fragments and number_patten.match(fragments[-1].strip()):
            values.insert(0, parse_number(fragments.pop()))
        row = {"label": " ".join(fragments).strip(), "values": values}

        # Re-join wrapped labels
        if rows and not rows[-1]["values"] and rows[-1]["label"] and values and row["label"][:1].islower():
            row["label"] = rows.pop()["label"] + " " + row["label"]

        rows.append(row)

    return rows


def is_year_row(row):
    """
    Check if a line contains a year (4-digit number)
    """
    # A year line has no label and at least 2 values, all of which are valid years
    # A valid year is a 4-digit number between 1990 and 2100
    # A valid year line is one that has no label and at least 2 values, all of which are valid years
    if row["label"]:
        return False
    if len(row["values"]) < 2:
        return False
    for value in row["values"]:
        if not isinstance(value, int) or value < 2000 or value > 2050:
            return False
    return True


def find_year(rows):
    """
    Find the year line (2024, 2025) from the year row
    """
    #  Find the first row that is a year line and return its values as a list of integers
    #  If no year line is found, return a list with two None values
    return next((r["values"][:2] for r in rows if is_year_row(r)), [None, None])


# Headings that start a table. Extend this list if other fillings have different headings.
section_headings = re.compile(
    r"^(employees|tangible fixed assets|cost|depreciation and impairment|"
    r"carrying amount|creditors: amounts falling due (within|after))", re.I)

# Subheadings that are within a parent heading
sub_headings = re.compile(r"(cost|depreciation|carrying)", re.I)

def tag_rows(rows):
    """
    Tag each row with headings and subheadings based on the content of the label.
    1. If the label matches a section heading, tag it as a section.
    2. If the label matches a sub-heading, tag it as a sub-heading.
    """
    section = ""
    tagged = []

    for row in rows:
        if not row["values"]:
            # If the row has no values, it might be a heading
            heading = re.sub(r"^\d+\s+", "", row["label"])
            if section_headings.match(heading):
                parent = section.split( " / ")[0]
                is_subheading = sub_headings.match(heading) and parent
                section = f"{parent} / {heading}" if is_subheading else heading
        elif not is_year_row(row):
            # Keep rows with values, but not the year row, and tag them with the current section
            tagged.append({"section": section,
                           "label": row["label"] or "Total",
                           "values": row["values"]})
    return tagged

def similar_label(label1, label2, threshold=0.9):
    """
    Check if two labels are similar enough to be considered the same.
    """
    return SequenceMatcher(None, label1.lower(), label2.lower()).ratio() >= threshold

def find_row(table, label, section=None):
    """
    Find a row in the table by label and optional section.
    Returns the row if found, otherwise None.
    """
    return next((row for row in table if similar_label(row["label"], label)
                 and (section is None or section.lower() in row["section"].lower())), None)

def two_year(row, years):
    """
    Format a rows last two values as {year: value} pairs, or None
    """
    if not row or len(row["values"]) < 2:
        return None
    return {str(years[0]): row["values"][-2], str(years[1]): row["values"][-1]}

def find_page(pages, anchor_text, expected, warnings, what):
    """
    Return the lines of the first page that contains the anchor_text, or None if not found.
    Expected is the 1st page number where the anchor_text is expected to be found, for warning purposes.
    Falls back to expected page if the anchor_text is not found in any page.
    """
    for i, lines in enumerate(pages):
        text = " ".join(lines).lower()
        if all(x in text for x in anchor_text):
            if i + 1 != expected:
                warnings.append(f"{what} found on page {i + 1}, expected page {expected}")
            return lines
    warnings.append(f"{what} not found, expected on page {expected}")
    return pages[min(expected, len(pages)) - 1] if pages else []


# Balance sheet labels mapping for better readability
balance_sheet_labels = {
    "tangible_assets": "Tangible Assets",
    "cash_at_bank_and_in_hand": "Cash at bank and in hand",
    "creditors_due_within_one_year": "Creditors: amounts falling due within one year",
    "net_current_liabilities": "Net Current Liabilities",
    "total_assets_less_current_liabilities": "Total Assets Less Current Liabilities",
    "creditors_due_after_more_than_one_year": "Creditors: amounts falling due after more than one year",
    "net_assets": "Net Assets",
    "called_up_share_capital": "Called Up Share Capital",
    "profit_and_loss_reserves": "Profit And Loss Reserves",
    "total_equity": "Total Equity",
}

# Arithmetic checks for balance sheet totals
# The total must equal the sum of its components, and net assets must equal total equity.
# Creditors are negative values, so they are subtracted from assets to calculate net assets.
balance_sheet_checks = [
    ("net current liabilities = cash + creditors due within one year",
     "net_current_liabilities", ["cash_at_bank_and_in_hand", "creditors_due_within_one_year"]),
    ("total assets less current liabilities = tangible assets + net current liabilities",
     "total_assets_less_current_liabilities", ["tangible_assets", "net_current_liabilities"]),
    ("net assets = total assets less current liabilities + creditors due after one year",
     "net_assets", ["total_assets_less_current_liabilities", "creditors_due_after_more_than_one_year"]),
    ("total equity = share capital + reserves",
     "total_equity", ["called_up_share_capital", "profit_and_loss_reserves"]),
    ("total equity = net assets", "total_equity", ["net_assets"]),
]


def parse_company(lines, address_lines, warnings):
    """
    Parse the company name, registration number, directors, balance sheet date, address.
    """
    text = " ".join(lines)

    # Company Registration Number (CRN) (8 digits)
    crn_number = re.search(r"registration number\s+([A-Z]{0,2}\d{6,8})", text, re.I)
    # Balance sheet date
    bs_date = re.search(r"AS AT\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, re.I)
    # Company Address
    c_address = re.search(r"registered office\s+is\s+(.+?)\.(?:\s|$)", address_lines, re.I)
    # Directors name
    d_name = [lines[i - 1].strip() for i, line in enumerate(lines) if i > 0
              and line.strip().lower() in ("director", "directors")]

    info = {
        # The first line is usually the company name, but if it's empty, we return None
        "name": lines[0].strip() if lines else None,
        "registration_number": crn_number.group(1) if crn_number else None,
        "directors": d_name[0] if d_name else None,
        "balance_sheet_date": bs_date.group(1) if bs_date else None,
        "address": c_address.group(1).strip() if c_address else None,
    }

    for key, value in info.items():
        if not value:
            warnings.append(f"Missing {key.replace('_', ' ')} not found in the document.")
    return info

def bs_sum(values):
    """
    Sum a list of values, None if any value is missing.
    """
    return None if None in values or values is None else sum(values)


def validate_balance_sheet(balance_sheet, carrying, creditors_total, warnings ):
    """
    Validate the balance sheet totals and return a list of warnings if any checks fail.
    A mismatch means an error in the OCR or parsing.
    """
    years = sorted({x for value in balance_sheet.values() if value for x in value}, reverse=True)

    for year in years:

        def fig(key):
            return (balance_sheet.get(key) or {}).get(year)

        within = fig("creditors_due_within_one_year")

        checks = [(desc, fig(total), bs_sum([fig(p) for p in parts]))
                  for desc, total, parts in balance_sheet_checks]

        checks += [
            ("note 'carrying amount' total = balance sheet tangible assets",
             carrying.get(year), fig("tangible_assets")),
            ("note creditors total = balance sheet creditors due within one year",
             creditors_total.get(year), None if within is None else -within),
        ]
        for desc, found, expected in checks:
            if found is not None and expected is not None and found != expected:
                warnings.append(f"Balance sheet check failed for {year}: {desc}. "
                                f"Found {found}, expected {expected}.")

def parse_accounts(pages_lines, source_file=""):
    """
    Parse the accounts from the OCR results of a PDF file.
    Returns a dictionary with company info, balance sheet, and warnings.
    """
    warnings = []

    # Locate content pages by their anchor text
    bs_lines = find_page(pages_lines, ["balance sheet", "total equity"], 3, warnings, "balance sheet")
    address_lines = find_page(pages_lines, ["registered office"], 4, warnings, "company address")
    notes_lines = find_page(pages_lines, ["employees", "amounts falling due"], 5, warnings, "notes to the accounts")

    company_info = parse_company(bs_lines, " ".join(address_lines), warnings)

    bs_rows = build_rows(bs_lines)
    years = find_year(bs_rows)
    company_info["years"] = years

    if years[0] is None:
        warnings.append("No valid year found in the balance sheet.")

    bs_table = tag_rows(bs_rows)
    balance_sheet = {}

    for key, label in balance_sheet_labels.items():
        balance_sheet[key] = two_year(find_row(bs_table, label), years)
        if balance_sheet[key] is None:
            warnings.append(f"Balance sheet item '{label}' not found.")

    note_rows = build_rows(notes_lines)
    note_years = find_year(note_rows)
    table = tag_rows(note_rows)

    employees = two_year(find_row(table, "Total", "Employees"), note_years)

    tangible = [{"section": row["section"].split(" / ")[-1],
                 "label": row["label"],
                 "total": row["values"][-1],
                 "values": row["values"]}
                for row in table if row["section"].startswith("tangible fixed assets")]

    def creditors_rows(section_start):
        """
        Rows of a creditors table with figures for both years
        """
        return [{"label": row["label"], "values": two_year(row, note_years)} for row in table
                if row["section"].lower().startswith(section_start) and len(row["values"]) >= 2]

    within = creditors_rows("creditors: amounts falling due within")
    after = creditors_rows("creditors: amounts falling due after")

    # Validate the balance sheet totals and return a list of warnings if any checks fail.
    carrying_rows = [t for t in tangible if t["section"].lower() == "carrying amount"]
    carrying = {str(y): t["total"] for y, t in zip(note_years, carrying_rows)}
    creditors_total = next((r["values"] for r in within if r["label"] == "Total"), None) or {}
    validate_balance_sheet(balance_sheet, carrying, creditors_total, warnings)

    return {
        "source_file": source_file,
        "company": company_info,
        "balance_sheet": balance_sheet,
        "employees_total": employees,
        "tangible_fixed_assets": tangible,
        "creditors_due_within_one_year": within,
        "creditors_due_after_more_than_one_year": after,
        "warnings": warnings,
    }
