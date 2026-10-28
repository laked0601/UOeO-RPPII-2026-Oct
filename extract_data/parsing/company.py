"""
Company details read from the text of the whole document.

Registration number, period end and approval date.  The company's name, address and directors
are deliberately not read: the registration number identifies the company.  OCR errors in the
company number are repaired using the number in the file name where available.
"""

import re
from collections import Counter

from extract_data.parsing.figures import find_dates

COMPANY_NUMBER = re.compile(
    r"(?:company\s+(?:registration\s+)?|registered\s+|registration\s+|llp\s+registered\s+)(?:number|no\.?)\s*[:\-]?\s*([A-Z]{0,2}\d{6,8})\b",
    re.I)
FILENAME = re.compile(r"^(?:(?P<number>[A-Z]{0,2}\d{6,8})_)?(?P<type>[A-Za-z0-9]{2,4})_(?P<date>\d{4}-\d{2}-\d{2})")
SIGNER = re.compile(r"^(?:directors?|designated members?)(?:\s+(?:date:?\s*)?\d.*)?$", re.I)

# Prefixes of company numbers that are not all digits (Companies House).
NUMBER_PREFIXES = {"AC", "CE", "CS", "FC", "FE", "GE", "GS", "IC", "IP", "LP", "NA", "NF", "NI", "NL", "NO", "NP",
                   "NR", "NZ", "OC", "OE", "PC", "R0", "RC", "SA", "SC", "SE", "SF", "SG", "SI", "SL", "SO", "SP",
                   "SR", "SZ", "ZC"}


def clean_company_number(text, from_filename=None):
    """
    Tidy a company number read by OCR, e.g. 'Nl033061' or 'N1019095' -> 'NI033061' / 'NI019095'.

    In the letters at the front, a lowercase l or the digit 1 is a capital I.  If the file name
    holds a number that differs only by such look-alike characters, the file name's is used.
    """
    text = re.sub(r"\s+", "", text)
    if from_filename:
        alike = lambda s: re.sub(r"[Il1]", "I", s.upper()).replace("O", "0")
        if alike(text) == alike(from_filename):
            return from_filename.upper()
    if len(text) == 8 and text[0].isalpha():
        second = {"l": "I", "1": "I"}.get(text[1], text[1]).upper()
        prefix = text[0].upper() + second
        if prefix in NUMBER_PREFIXES or text[:2].upper() not in NUMBER_PREFIXES:
            return prefix + text[2:]
    return text.upper()


def find_period_end(everything, tables):
    """
    The accounting period end.

    The date most often given as "for the year ended ...", else the date printed above a
    statement ("as at ..."), else the latest dated column.
    """
    ended = Counter()
    for m in re.finditer(r"(?:year|period)\s+ended\s*:?\s*(.{0,30})", everything, re.I):
        found = find_dates(m.group(1))
        if found:
            ended[found[0]] += 1
    hints = Counter(t["date_hint"] for t in tables if t["date_hint"])
    dated = [c["period_end"] for t in tables for c in t["columns"] or [] if c["period_end"]]
    if ended:
        return max(ended, key=lambda d: (ended[d], d))  # ties go to the later date
    if hints:
        return max(hints, key=lambda d: (hints[d], d))
    return max(dated) if dated else None


def find_approval_date(all_lines, everything):
    """
    The date the accounts were approved.

    The first date printed beside a signature ("Director  28 April 2016"), else a date in an
    "approved ... on <date>" sentence.
    """
    for line in all_lines:
        if SIGNER.match(line.strip()):
            dates = find_dates(line)
            if dates:
                return dates[0]
    m = re.search(r"(?:approved|authorised for issue|signed)\b.{0,150}?\bon\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                  everything, re.I)
    found = find_dates(m.group(1)) if m else []
    return found[0] if found else None


def find_company_number(head, file_number, warnings):
    """
    The registration number: read from the first pages, else from the file name.

    OCR errors are repaired using the file name's number, and a real difference is reported.
    """
    found = COMPANY_NUMBER.search(head)
    number = clean_company_number(found.group(1), file_number) if found else file_number
    if number and file_number and number != file_number.upper():
        warnings.append(f"registration number {number} in the document differs from {file_number} in the file name")
    return number


def filing_details(filing):
    """The company number, type ("aa" = annual accounts) and date given in the file name, if any."""
    if not filing:
        return None
    return {"company_number": filing.group("number"), "type": filing.group("type"), "date": filing.group("date")}


def extract_company(pages_lines, tables, source_file, warnings):
    """Company number, period end and approval date; also the filing details from the file name."""
    head = " ".join(" ".join(lines) for lines in pages_lines[:3])
    all_lines = [line for lines in pages_lines for line in lines]
    everything = " ".join(all_lines)

    filing = FILENAME.match(source_file or "")
    number = find_company_number(head, filing.group("number") if filing else None, warnings)
    period_end = find_period_end(everything, tables)
    approval = find_approval_date(all_lines, everything)

    for label, value in (("registration number", number), ("period end", period_end)):
        if not value:
            warnings.append(f"{label} not found")

    iso = lambda d: d.isoformat() if d else None
    company = {"registration_number": number, "period_end": iso(period_end),
               "approval_date": iso(approval)}
    return company, filing_details(filing), period_end
