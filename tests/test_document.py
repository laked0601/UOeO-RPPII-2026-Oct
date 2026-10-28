"""
Tests for extract_data.parsing.document.

The fixtures in tests/fixtures are the saved OCR output (rows of positioned fragments per page) of
two real filings, so the tests run without repeating the slow OCR step:
  * 11508952_aa_2025-09-23      small company accounts (GBP, pounds)
  * companies_house_document    Shell plc interim accounts (USD, millions)
"""

import copy
import json
from datetime import date

import pytest

from extract_data.parsing.document import extract_document
from extract_data.parsing.figures import detect_units, find_dates, to_number
from support import extract, load_pages, row


def statement(result, name):
    return next(s for s in result["statements"] if s["name"] == name)


# ---------------------------------------------------------------- helpers


def test_to_number():
    assert to_number("773,374") == 773374
    assert to_number("(344,458)") == -344458
    assert to_number("26.887") == 26887  # OCR read a thousands comma as a full stop
    assert to_number("214,. 125") == 214125  # stray dot inside a figure
    assert to_number("7,667.") == 7667  # full stop after a figure
    assert to_number("(229, 190)") == -229190  # space after the comma
    assert to_number("0.07") == 0.07  # real decimals stay decimals
    assert to_number("-") == 0  # a dash means nil
    assert to_number("Total") is None


def test_find_dates_handles_both_orders_and_ocr_full_stops():
    assert find_dates("31 AUGUST 2025") == [date(2025, 8, 31)]
    assert find_dates("to December 31, 2025") == [date(2025, 12, 31)]
    assert find_dates("December 31. 2024") == [date(2024, 12, 31)]  # OCR: comma -> full stop
    assert find_dates("January 1") == []  # no year, no date


def test_detect_units_accepts_ocr_s_for_dollar():
    assert detect_units("$ million") == ("USD", 1_000_000)
    assert detect_units("S million") == ("USD", 1_000_000)
    assert detect_units("£'000") == ("GBP", 1_000)
    assert detect_units("Notes") == (None, None)


def test_shell_company_details():
    result = extract("companies_house_document")
    company = result["company"]
    assert company["registration_number"] == "04366849"
    assert company["period_end"] == "2025-12-31"
    assert company["approval_date"] == "2026-02-05"
    assert (company["currency"], company["unit_multiplier"]) == ("USD", 1_000_000)
    assert result["warnings"] == []


def test_shell_finds_all_statements():
    result = extract("companies_house_document")
    assert [s["name"] for s in result["statements"]] == [
        "Statement of income", "Statement of comprehensive income",
        "Statement of retained earnings", "Balance sheet"]


def test_shell_columns_come_from_dates_not_years():
    result = extract("companies_house_document")
    columns = statement(result, "Balance sheet")["columns"]
    assert [(c["key"], c["status"]) for c in columns] == [
        ("2025-12-31", "Unaudited"), ("2024-12-31", "Audited")]


def test_shell_second_statement_on_page_reuses_columns():
    result = extract("companies_house_document")
    columns = statement(result, "Statement of retained earnings")["columns"]
    assert [c["key"] for c in columns] == ["2025-12-31", "2024-12-31"]


def test_shell_balance_sheet_figures_and_totals():
    result = extract("companies_house_document")
    sheet = statement(result, "Balance sheet")
    assert row(sheet, "Total assets")["values"] == {"2025-12-31": 267083, "2024-12-31": 265047}
    assert row(sheet, "Total assets")["kind"] == "total"
    assert row(sheet, "Total equity")["standard"] == "total_equity"
    assert row(sheet, "Investments in subsidiaries")["note"] == "2"  # "(Note 2)" split off the label
    assert row(sheet, "Total liabilities and equity")["values"]["2025-12-31"] == 267083


def test_shell_dropped_figure_is_assumed_nil_when_totals_need_it():
    result = extract("companies_house_document")
    cash = row(statement(result, "Balance sheet"), "Cash and cash equivalents")
    assert cash["values"] == {"2025-12-31": 0, "2024-12-31": 0}
    assert "no_figures_read" in cash["flags"]


def test_shell_income_statement_negatives_and_totals():
    result = extract("companies_house_document")
    income = statement(result, "Statement of income")
    assert row(income, "Administrative expenses")["values"]["2025-12-31"] == -401
    assert row(income, "Income before taxation")["kind"] == "total"
    assert row(income, "Income for the period")["values"]["2024-12-31"] == 18493


def test_ocr_digit_error_in_a_total_is_reported():
    pages = load_pages("companies_house_document")
    broken = copy.deepcopy(pages)
    for row in broken[2]:
        if row[0][1] == "Total equity":
            row[1][1] = row[1][1].replace("265,441", "265,841")
    warnings = extract_document(broken, "x.pdf")["warnings"]
    assert any("Total equity" in w and "265,841" in w for w in warnings)


# ------------------------------- J White Properties (small company layout)


def test_small_company_figures_and_company_number():
    result = extract("11508952_aa_2025-09-23")
    sheet = statement(result, "Balance sheet")
    assert row(sheet, "Net assets")["values"] == {"2025-08-31": 20326, "2024-08-31": 20169}
    assert row(sheet, "Total equity")["values"] == {"2025-08-31": 20326, "2024-08-31": 20169}
    employees = next(t for t in result["note_tables"] if t["name"] == "Employees")
    assert row(employees, "Total")["values"] == {"2025-08-31": 1, "2024-08-31": 1}
    assert result["company"]["registration_number"] == "11508952"
    assert result["warnings"] == []


def test_small_company_gets_tables_and_filing_details():
    result = extract("11508952_aa_2025-09-23")
    assert result["filing"] == {"company_number": "11508952", "type": "aa", "date": "2025-09-23"}
    sheet = statement(result, "Balance sheet")
    assert [c["key"] for c in sheet["columns"]] == ["2025-08-31", "2024-08-31"]  # year columns -> period end dates
    assert row(sheet, "Net assets")["kind"] == "total"
    assert row(sheet, "Tangible assets")["note"] == "3"  # bare "3" from the Notes column
    assert result["company"]["period_end"] == "2025-08-31"
    assert result["company"]["currency"] == "GBP"


def test_small_company_note_tables():
    result = extract("11508952_aa_2025-09-23")
    names = [t["name"] for t in result["note_tables"]]
    assert names == ["Employees", "Tangible fixed assets",
                     "Creditors: amounts falling due within one year",
                     "Creditors: amounts falling due after more than one year"]
    tangible = next(t for t in result["note_tables"] if t["name"] == "Tangible fixed assets")
    assert [c["key"] for c in tangible["columns"]] == [
        "freehold_land_and_buildings", "plant_and_equipment", "total"]
    depreciation = row(tangible, "Depreciation charged in the year")
    assert list(depreciation["values"].values()) == [None, 213, 213]  # nil cell the OCR dropped
    assert "aligned_by_position" in depreciation["flags"]


def test_contents_page_is_not_treated_as_a_table():
    result = extract("11508952_aa_2025-09-23")
    assert all(t["page"] != 2 for t in result["statements"] + result["note_tables"])


@pytest.mark.parametrize("stem", ["11508952_aa_2025-09-23", "companies_house_document"])
def test_output_is_json_serialisable(stem):
    result = extract(stem)
    json.dumps(result)


# ------------------------------------------------------------- currency


def test_currency_defaults_to_pounds_and_says_so_when_none_is_found():
    from extract_data.parsing.document import most_common_currency
    assert most_common_currency([], [["Balance sheet", "Fixed assets  10  20"]]) == ("GBP", 1, True)
    assert most_common_currency([], [["Amounts in sterling"]]) == ("GBP", 1, False)
    table = {"currency": "USD", "unit_multiplier": 1_000_000}
    assert most_common_currency([table, table], [[]]) == ("USD", 1_000_000, False)
