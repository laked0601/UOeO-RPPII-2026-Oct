"""
Reading figures, dates and currencies out of OCR text.

The lowest layer of the generic extractor: it knows nothing about tables.  OCR
often damages numbers (the thousands separators especially), so `to_number`
repairs the common mistakes; dates and currency/unit hints are read from the
text of headings.
"""

import calendar
import re
from datetime import date

DASH = re.compile(r"^[-–—]+$")
NUMBER_TOKEN = re.compile(r"^\(?-?[\d.,]+\)?$")
PLAIN_NUMBER = re.compile(r"^(\()?(-)?(\d+)(\))?$")  # a whole number with no separators
DECIMAL = re.compile(r"^(\()?(-)?(\d{1,3}(?:,\d{3})*|\d+)\.(\d+)(\))?$")
# A whole-pound figure with thousands separators.  The OCR often misreads the
# separators: "26.887" (full stop), "(229, 190)" (extra space), "214,. 125" (stray dot).
THOUSANDS = re.compile(r"^(\()?(-)?(\d{1,3})((?:\s*[.,;:]+\s*\d{3})+)(\))?$")
# Looks like a figure but cannot be read, e.g. "(932,9865)": kept as an unknown value so the
# rest of the row (and its alignment) survives.
UNREADABLE = re.compile(r"^\(?-?\d[\d.,;: ]*\)?$")
YEAR_TOKEN = re.compile(r"^(?:19|20)\d{2}$")


def to_number(token):
    """
    Convert one text fragment to a number, or None if it is not a figure.

    * "773,374" -> 773374, "(344,458)" -> -344458
    * "26.887", "(229, 190)", "214,. 125" -> 26887, -229190, 214125
      (the OCR misreads thousands separators; accounts are in whole units)
    * "0.07" -> 0.07 (genuine decimals, e.g. per-share figures, stay decimal)
    * "-" -> 0 (a dash in an accounts table means nil)
    """
    token = token.strip()

    if DASH.match(token):
        return 0

    if re.search(r"[\d)][.,]$", token):  # "7,667." - a full stop after the figure
        token = token[:-1]
    thousands = THOUSANDS.match(token)

    if thousands:
        return signed(int(thousands.group(3) + re.sub(r"\D", "", thousands.group(4))), thousands)

    if not NUMBER_TOKEN.match(token):
        return None

    plain = PLAIN_NUMBER.match(token)

    if plain:
        return signed(int(plain.group(3)), plain)

    decimal = DECIMAL.match(token)

    if decimal:
        return signed(float(decimal.group(3).replace(",", "") + "." + decimal.group(4)), decimal)

    return None


def signed(value, match):
    """
    `value`, made negative if the match started with a bracket or a minus sign (groups 1 and 2).
    """
    return -value if match.group(1) or match.group(2) else value


def is_year_row(row):
    """
    True if every figure in the row is written as a bare year ("2025", not "2,025").

    Looking at the printed text, not the number, stops a row of genuine
    figures such as "Share capital  2,000  2,000" being mistaken for a header.
    """
    return len(row["tokens"]) >= 2 and all(YEAR_TOKEN.match(t) for t in row["tokens"])


def same(a, b):
    """Compare two figures; whole numbers must match exactly."""
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    return abs(a - b) <= 0.0051


# Dates

MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): number for number, name in enumerate(calendar.month_abbr) if name})

DATE_DMY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})")  # 31 August 2025
DATE_MDY = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,.]?\s+(\d{4})")  # December 31, 2025


def make_date(year, month_text, day):
    """
    Build a date from text parts, or None if they are not a real date.
    """
    month = MONTHS.get(month_text.lower())

    if not month:
        return None

    try:
        return date(int(year), month, int(day))

    except ValueError:
        return None


def find_dates(text):
    """
    All dates written in `text`, in the order they appear.
    """
    found = []

    for m in DATE_DMY.finditer(text):
        d = make_date(m.group(3), m.group(2), m.group(1))

        if d:
            found.append((m.start(), d))

    for m in DATE_MDY.finditer(text):
        d = make_date(m.group(3), m.group(1), m.group(2))

        if d:
            found.append((m.start(), d))

    return [d for _, d in sorted(found)]


# Currency and units

# "$ million", "£'000", "£000".  OCR often reads "$" as "S", so a capital S
# is accepted, but only when a unit word follows it.
UNITS = re.compile(r"([£$€S])\s*['’]?\s*(million|mn|m|bn|billion|thousand|000|k)\b", re.I)
CURRENCY_SYMBOL = {"£": "GBP", "$": "USD", "S": "USD", "€": "EUR"}
MULTIPLIER = {"million": 1_000_000, "mn": 1_000_000, "m": 1_000_000,
              "bn": 1_000_000_000, "billion": 1_000_000_000,
              "thousand": 1_000, "000": 1_000, "k": 1_000}


def detect_units(text):
    """
    Return (currency, multiplier) found in header text, e.g. ('USD', 1000000).
    """
    m = UNITS.search(text)
    if m:
        return CURRENCY_SYMBOL[m.group(1).upper()], MULTIPLIER[m.group(2).lower()]

    for symbol in "£$€":
        if symbol in text:
            return CURRENCY_SYMBOL[symbol], 1

    return None, None
