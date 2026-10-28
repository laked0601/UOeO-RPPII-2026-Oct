"""
Tests for two more real filings and the parser fixes they needed.

Fixtures (saved OCR output with fragment positions, see test_layouts.py):
  * NI033061_aa_2022-04-29            micro-entity balance sheet only, three pages, OCR-misread company number
  * uk_offshore_energies_group_2025   full group accounts: all-capitals labels, wrapped labels, Group and
                                      Company columns in one table, notes in two column layouts
"""

import json
from extract_data.parsing.company import clean_company_number
from extract_data.parsing.document import extract_document
from extract_data.parsing.labels import standard_label
from extract_data.parsing.rows import read_rows
from extract_data.results.standardise import standardise
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def extract(name):
    pages = json.loads((FIXTURES / f"{name}.ocr.json").read_text(encoding="utf-8"))
    return extract_document(pages, f"{name}.pdf")


def table(result, name):
    return next(t for t in result["statements"] + result["note_tables"] if t["name"] == name)


def row(t, label, nth=0):
    return [r for r in t["rows"] if r["label"] == label][nth]


def figures(r):
    return list(r["values"].values())


def standard_row(t, heading):
    return next(r for r in t["rows"] if r.get("standard") == heading)


# ------------------------------------------------------------- parser fixes


def test_figures_run_together_in_one_fragment_are_split():
    rows = read_rows([[(0, "Administration expenses", 300), (310, "(11,756,310)(12,027,711)", 600)]])
    assert rows[0]["label"] == "Administration expenses"
    assert rows[0]["values"] == [-11756310, -12027711]


def test_an_unreadable_figure_keeps_the_row_and_the_others():
    rows = read_rows([[(0, "Income not taxable", 300), (310, "(950,929)", 400), (410, "(932,9865)", 520)]])
    assert rows[0]["label"] == "Income not taxable"
    assert rows[0]["values"] == [-950929, None]


def test_semicolon_and_stray_dot_inside_figures():
    rows = read_rows([[(0, "Cash", 100), (110, "6,776,115·", 200), (210, "(4;009,479)", 300)]])
    assert rows[0]["values"] == [6776115, -4009479]


def test_uppercase_label_wrapped_after_a_joining_word_is_joined():
    rows = read_rows(["TOTAL ASSETS LESS CURRENT", "LIABILITIES  1,835,176  2,321,369"])
    assert [r["label"] for r in rows] == ["TOTAL ASSETS LESS CURRENT LIABILITIES"]
    assert rows[0]["values"] == [1835176, 2321369]


def test_short_line_finishing_the_label_above_is_joined():
    rows = read_rows(["SURPLUS / (DEFICIT) ON", "ORDINARY ACTIVITIES  3  64,364  (356,072)", "BEFORE TAXATION"])
    assert [r["label"] for r in rows] == ["SURPLUS / (DEFICIT) ON ORDINARY ACTIVITIES BEFORE TAXATION"]


def test_headings_ending_in_a_colon_or_a_noun_are_not_joined_to_the_next_row():
    assert len(read_rows(["Represented by:", "Revenue Reserves  1,776,018  1,746,349"])) == 2
    assert len(read_rows(["Carrying amount", "At 31 August 2025  100  200"])) == 2  # "amount" does not continue a label


def test_standard_labels_ignore_spaces_around_slashes():
    assert standard_label("SURPLUS / (DEFICIT) ON ORDINARY ACTIVITIES BEFORE TAXATION") == "profit_before_tax"
    assert standard_label("Gross surplus") == "gross_profit"
    assert standard_label("Revenue Reserves") == "retained_earnings"
    assert standard_label("Provision for deferred taxation") == "deferred_tax"


def test_company_numbers_misread_by_ocr_are_repaired():
    assert clean_company_number("Nl033061") == "NI033061"  # lowercase l for I
    assert clean_company_number("N1019095") == "NI019095"  # digit 1 for I
    assert clean_company_number("NL033061") == "NL033061"  # a real prefix is left alone
    assert clean_company_number("05421996") == "05421996"
    assert clean_company_number("Nl033061", "NI033061") == "NI033061"  # the file name settles it


# ----------------------------------------------- micro-entity (3 pages)


def test_micro_entity_company_details():
    result = extract("NI033061_aa_2022-04-29")
    company = result["company"]
    assert company["registration_number"] == "NI033061"  # OCR read "Nl033061"
    assert company["period_end"] == "2021-07-31"
    assert company["approval_date"] == "2022-04-29"
    assert result["filing"]["company_number"] == "NI033061"
    assert result["warnings"] == []


def test_micro_entity_balance_sheet_and_standard_headings():
    result = extract("NI033061_aa_2022-04-29")
    sheet = table(result, "Balance sheet")
    assert [c["key"] for c in sheet["columns"]] == ["2021-07-31", "2020-07-31"]
    assert row(sheet, "Net Liabilities")["standard"] == "net_assets"
    assert row(sheet, "Capital and Reserves")["standard"] == "total_equity"
    standardised = standardise(result)
    assert standardised["unmapped"] == []
    now = standardised["entities"]["company"]["periods"]["2021-07-31"]
    assert now["assets"]["current_assets"] == 90000
    assert now["net_assets"]["net_assets"] == -19830
    assert now["capital_and_reserves"]["total_equity"] == -19830


# ----------------------------------------- full group accounts (26 pages)


def test_group_accounts_company_details():
    result = extract("uk_offshore_energies_group_2025")
    company = result["company"]
    assert company["registration_number"] == "01119804"
    assert company["period_end"] == "2025-12-31"
    assert company["approval_date"] == "2026-06-17"


def test_each_statement_is_separate():
    result = extract("uk_offshore_energies_group_2025")
    assert [s["name"] for s in result["statements"]] == [
        "Consolidated statement of comprehensive income",
        "Consolidated and company statements of financial position",
        "Consolidated cash flow statement",
        "Consolidated statements of changes in equity"]


def test_income_statement_with_wrapped_all_capitals_labels():
    income = table(extract("uk_offshore_energies_group_2025"), "Consolidated statement of comprehensive income")
    assert figures(row(income, "Administration expenses")) == [-11756310, -12027711]
    gross = standard_row(income, "gross_profit")
    assert gross["kind"] == "total" and figures(gross) == [11610714, 11399657]
    before_tax = standard_row(income, "profit_before_tax")
    assert before_tax["label"].endswith("ORDINARY ACTIVITIES BEFORE TAXATION") and before_tax["note"] == "3"
    assert figures(before_tax) == [64364, -356072]
    assert figures(standard_row(income, "profit_for_period")) == [29669, -414283]


def test_group_and_company_columns_in_one_statement():
    sheet = table(extract("uk_offshore_energies_group_2025"),
                  "Consolidated and company statements of financial position")
    assert [c["key"] for c in sheet["columns"]] == [
        "2025-12-31_group", "2024-12-31_group", "2025-12-31_company", "2024-12-31_company"]
    assert figures(row(sheet, "Tangible assets")) == [482680, 450408, 482680, 450408]  # "482;680" repaired
    assert figures(row(sheet, "Investment in Subsidiary")) == [None, None, 67052, None]
    creditors = standard_row(sheet, "creditors_within_one_year")
    assert figures(creditors) == [-5889969, -6098834, -4323459, -4798704]
    assert "values_on_next_line" in creditors["flags"]
    assert row(sheet, "TOTAL ASSETS LESS CURRENT LIABILITIES")["kind"] == "total"
    assert row(sheet, "NET ASSETS")["kind"] == "total"
    assert figures(row(sheet, "Revenue Reserves")) == [1776018, 1746349, 2195022, 2175549]


def test_cash_flow_and_equity_statements_do_not_swallow_each_other():
    result = extract("uk_offshore_energies_group_2025")
    equity = table(result, "Consolidated statements of changes in equity")
    assert [r["section"] for r in equity["rows"]][0] == "Group" and equity["rows"][-1]["section"] == "Company"
    cash_flow = table(result, "Consolidated cash flow statement")
    assert all(not r["label"].startswith("At ") for r in cash_flow["rows"])


def test_note_tables_with_group_and_company_columns():
    debtors = table(extract("uk_offshore_energies_group_2025"), "DEBTORS")
    assert [c["key"] for c in debtors["columns"]] == [
        "2025-12-31_group", "2024-12-31_group", "2025-12-31_company", "2024-12-31_company"]
    assert figures(row(debtors, "Amounts due from group undertakings")) == [None, None, 101570, 98163]


def test_net_debt_table_opening_column_is_the_previous_year_end():
    net_debt = table(extract("uk_offshore_energies_group_2025"), "ANALYSIS OF CHANGES IN NET DEBT")
    assert net_debt["columns"][0]["key"] == "2024-12-31"  # "At 1 Jan 2025"
    assert figures(row(net_debt, "Cash")) == [6776115, -4009479, 2766636]  # semicolon and stray dot repaired


def test_tax_reconciliation_that_starts_from_a_base_figure():
    result = extract("uk_offshore_energies_group_2025")
    tax = table(result, "Factors affecting tax charge for the year")
    total = row(tax, "Total tax charge/(credit)")
    assert total["kind"] == "total"  # 2025 adds up once the first row is left out
    income = row(tax, "Income not taxable for tax purposes")
    assert figures(income) == [-950929, None] and "unreadable_figure" in income["flags"]


def test_only_warning_is_the_figure_the_filing_prints_wrongly():
    warnings = extract("uk_offshore_energies_group_2025")["warnings"]
    assert len(warnings) == 1
    assert "2024-12-31" in warnings[0] and "Income not taxable for tax purposes" in warnings[0]
    assert "could not be read" in warnings[0]


def test_group_accounts_standardised_by_entity():
    result = standardise(extract("uk_offshore_energies_group_2025"))
    assert list(result["entities"]) == ["group", "company"]
    group = result["entities"]["group"]["periods"]["2025-12-31"]
    company = result["entities"]["company"]["periods"]["2025-12-31"]
    assert group["income"]["turnover"] == 14999516
    assert group["profit_and_loss"]["profit_before_tax"] == 64364
    assert group["profit_and_loss"]["profit_for_period"] == 29669
    assert group["assets"]["debtors"] == 975829 and company["assets"]["debtors"] == 1300849
    assert company["assets"]["investments"] == 67052 and group["assets"]["investments"] is None
    assert group["creditors"]["deferred_tax"] == -59158
    assert group["capital_and_reserves"]["retained_earnings"] == 1776018
    assert company["income"]["turnover"] is None  # the company has no income statement
    assert result["unmapped"] == [] and result["conflicts"] == []  # cash flow rows are not mapped


def test_accumulated_depreciation_is_found_in_the_note():
    group = standardise(extract("uk_offshore_energies_group_2025"))["entities"]["group"]["periods"]
    assert group["2025-12-31"]["depreciation"] == {
        "tangible_cost": 1392555, "depreciation_charge": 165133,
        "accumulated_depreciation": 909875, "net_book_value": 482680}
    assert group["2024-12-31"]["depreciation"]["net_book_value"] == 450408
    assert group["2024-12-31"]["depreciation"]["accumulated_depreciation"] == 774371  # "At 1 January 2025"
