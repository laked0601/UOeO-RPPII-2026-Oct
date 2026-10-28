"""
Tests for extract_data.parsing.document on filings with different layouts, and the parser fixes they needed.

Each fixture in tests/fixtures/*.ocr.json is the saved OCR output (with the
horizontal position of every fragment) of one real filing:
  * crown_overseas_abbreviated_2015   abbreviated accounts, "Notes  2015  2014" header
  * 05421996_aa_2026-05-26            small company accounts, tables running over a page
  * epic_im_llp_group_2025            group LLP accounts: Consolidated and LLP columns,
                                      five-column member statements, blank cells everywhere
                                      (prose pages are blanked in the fixture to keep it small)
  * NI033061_aa_2022-04-29            micro-entity balance sheet only, three pages, OCR-misread company number
  * uk_offshore_energies_group_2025   full group accounts: all-capitals labels, wrapped labels, Group and
                                      Company columns in one table, notes in two column layouts
  * 11508952_aa_2025-09-23, companies_house_document   the two layouts used in test_document.py

Warnings that these tests expect for the LLP filing are genuine: the scan itself
contains inconsistent totals, or the OCR misread a dash as "1".
"""

import pytest

from extract_data.parsing.company import clean_company_number
from extract_data.parsing.figures import is_year_row
from extract_data.parsing.labels import standard_label
from extract_data.parsing.rows import read_rows, TRAILING_NUMBERS
from extract_data.parsing.tables import STATEMENT_HEADING
from extract_data.results.standardise import standardise
from support import extract, figures, row, table, text_row


def test_figures_merged_into_the_label_are_split_off():
    rows = read_rows([[(0, "At 31 March 2025 124,556 7,667.", 400), (410, "549,402", 480), (490, "654,876", 560)]])
    assert rows[0]["label"] == "At 31 March 2025"
    assert rows[0]["values"] == [124556, 7667, 549402, 654876]
    assert TRAILING_NUMBERS.match("Cost of sales (213, 135)")


def test_stray_dots_are_dropped_but_dashes_kept():
    rows = read_rows([[(0, "Trade debtors", 100), (200, ".", 205), (300, "-", 310), (400, "83,502", 470)]])
    assert rows[0]["label"] == "Trade debtors"
    assert rows[0]["values"] == [0, 83502]


def test_year_row_needs_bare_years_not_figures():
    assert is_year_row(read_rows([text_row("Notes  2026  2025")])[0])
    assert not is_year_row(read_rows([text_row("Share capital  2,000  2,000")])[0])


def test_statement_headings_with_prefixes():
    for heading in ("Abbreviated Balance Sheet", "LLP STATEMENT OF FINANCIAL POSITION",
                    "CONSOLIDATED STATEMENT OF CHANGES IN MEMBERS' INTEREST", "Balance Sheet as at 30 April 2026"):
        assert STATEMENT_HEADING.match(heading), heading


def test_standard_labels_are_exact_not_fuzzy():
    assert standard_label("Intangible assets") == "intangible_assets"  # not "tangible_assets"
    assert standard_label("Tangible assets") == "tangible_assets"
    assert standard_label("Debtors: amounts falling due within one year") == "debtors"
    assert standard_label("Investments in subsidiaries (Note 2)") == "investments"
    assert standard_label("Something unusual") is None


# --------------------------------------------- abbreviated accounts (2015)


def test_abbreviated_accounts_company_details():
    company = extract("crown_overseas_abbreviated_2015")["company"]
    assert company["registration_number"] == "NI019095"
    assert company["period_end"] == "2015-04-30"
    assert company["approval_date"] == "2016-04-28"


def test_abbreviated_balance_sheet_is_found_and_notes_row_is_a_header():
    result = extract("crown_overseas_abbreviated_2015")
    sheet = table(result, "Abbreviated balance sheet")
    assert [c["key"] for c in sheet["columns"]] == ["2015-04-30", "2014-04-30"]
    assert all(r["label"] != "Notes" for r in sheet["rows"])
    assert row(sheet, "Tangible assets")["note"] == "2"
    assert row(sheet, "Total assets less current liabilities")["kind"] == "total"
    assert row(sheet, "Shareholders' funds")["standard"] == "total_equity"
    assert figures(row(sheet, "Profit and loss account")) == [-13392, -13233]
    assert result["warnings"] == []


def test_subtotal_feeds_the_next_total():
    # "Net current liabilities" is the subtotal (7,355) less creditors (32,347).
    sheet = table(extract("crown_overseas_abbreviated_2015"), "Abbreviated balance sheet")
    net_current = row(sheet, "Net current liabilities")
    assert net_current["kind"] == "total"
    assert figures(net_current) == [-24992, -20940]


# ---------------------------------- tables that run over a page (2026)


def test_small_company_details():
    result = extract("05421996_aa_2026-05-26")
    company = result["company"]
    assert company["period_end"] == "2026-04-30"
    assert result["filing"]["company_number"] == "05421996"
    assert result["warnings"] == []


def test_no_junk_tables_from_cover_page_or_registered_number():
    result = extract("05421996_aa_2026-05-26")
    assert [t["name"] for t in result["note_tables"]] == [
        "Employees", "Tangible fixed assets", "Debtors", "Creditors: amounts falling due within one year"]


def test_table_continues_on_the_next_page():
    tangible = table(extract("05421996_aa_2026-05-26"), "Tangible fixed assets")
    assert [c["key"] for c in tangible["columns"]] == ["plant_and_machinery_etc", "motor_vehicles", "total"]
    assert figures(row(tangible, "At 1 May 2025")) == [68212, 123719, 191931]  # page 5
    assert figures(row(tangible, "Additions")) == [16306, 43044, 59350]  # page 6
    assert figures(row(tangible, "On disposals")) == [None, -28430, -28430]


def test_lone_figure_is_placed_by_its_position():
    # The scan shows "4" under both years; the OCR only found the one under 2025.
    employees = table(extract("05421996_aa_2026-05-26"), "Employees")
    entry = row(employees, "Average number of persons employed by the company")
    assert entry["values"]["2025-04-30"] == 4
    assert "aligned_by_position" in entry["flags"]


# ------------------------------------------------ group LLP accounts (2025)


def test_llp_company_details():
    company = extract("epic_im_llp_group_2025")["company"]
    assert company["registration_number"] == "OC437064"
    assert company["period_end"] == "2025-03-31"


def test_llp_statements_found():
    result = extract("epic_im_llp_group_2025")
    assert [s["name"] for s in result["statements"]] == [
        "Consolidated statement of comprehensive income", "Consolidated statement of financial position",
        "LLP statement of financial position", "Consolidated statement of changes in members' interest",
        "LLP statement of changes in members' interest"]


def test_split_and_garbled_figures_in_the_income_statement():
    income = table(extract("epic_im_llp_group_2025"), "Consolidated statement of comprehensive income")
    assert row(income, "Turnover")["label"] == "Turnover"  # leading ". " removed
    assert figures(row(income, "Cost of sales")) == [-213135, -223251]  # "(213, 135)" repaired
    assert row(income, "Gross profit")["kind"] == "total"


def test_group_balance_sheet_chains_subtotals_into_totals():
    sheet = table(extract("epic_im_llp_group_2025"), "Consolidated statement of financial position")
    assert row(sheet, "Net current assets")["kind"] == "total"
    assert row(sheet, "Total assets less current liabilities")["kind"] == "total"
    assert figures(row(sheet, "Net assets")) == [-617740, -1229260]
    investments = row(sheet, "Investments")
    assert investments["note"] == "12"  # note ref, not a figure
    assert figures(investments) == [0, 0]
    assert any(f.startswith("nil_assumed") for f in investments["flags"])


def test_member_statement_places_figures_under_five_columns():
    t = table(extract("epic_im_llp_group_2025"), "Consolidated statement of changes in members' interest")
    assert [c["key"] for c in t["columns"]] == [
        "members_capital", "loans_and_other_debts_due", "profit_and_loss_account",
        "non_controlling_interests", "total"]
    assert figures(row(t, "Loss for the financial period")) == [None, None, -822476, None, -822476]
    assert figures(row(t, "Capital withdrawn on member resignation")) == [-34000, None, None, None, -34000]


def test_figures_printed_on_the_line_below_their_label_are_joined():
    t = table(extract("epic_im_llp_group_2025"), "Consolidated statement of changes in members' interest")
    opening = row(t, "Members' interest at 1 April 2024")
    assert figures(opening) == [361003, -1499816, -90873, 426, -1229260]
    assert "values_on_next_line" in opening["flags"]


def test_garbled_opening_balance_is_not_mistaken_for_a_header():
    t = table(extract("epic_im_llp_group_2025"), "LLP statement of changes in members' interest")
    assert [c["key"] for c in t["columns"]] == [
        "members_capital", "loans_and_other_debts_due", "profit_and_loss_account", "total"]
    assert figures(row(t, "Members' interest as at 1 April 2023")) == [395003, -1068570, 887692, 214125]


def test_consolidated_and_llp_columns_stay_separate_with_blank_cells():
    debtors = table(extract("epic_im_llp_group_2025"), "Debtors")
    assert [c["key"] for c in debtors["columns"]] == [
        "2025-03-31_consolidated", "2025-03-31_llp", "2024-03-31_consolidated", "2024-03-31_llp"]
    assert figures(row(debtors, "Trade debtors")) == [11838, None, 83502, None]
    assert figures(row(debtors, "VAT")) == [30470, None, 32437, 3270]
    assert figures(row(debtors, "Prepayments")) == [83293, 351, 130391, 834]


def test_multi_line_column_heading_is_joined():
    intangible = table(extract("epic_im_llp_group_2025"), "Intangible assets")
    assert [c["key"] for c in intangible["columns"]] == ["goodwill", "software", "management_mandate", "total"]
    # "7,667." (with a stray full stop) and the two figures merged into the label.
    assert figures(row(intangible, "At 31 March 2025", 1)) == [124556, 7667, 549402, 654876]


def test_group_headed_by_a_line_ending_in_a_colon_is_its_own_section():
    # "Fees for the audit of ... subsidiary undertakings:" starts a second group, so the
    # final 30,125 sums only that group (and the unprinted Guernsey fee is taken as nil).
    result = extract("epic_im_llp_group_2025")
    fees = table(result, "Auditor's remuneration")
    assert figures(row(fees, "EEA Fund Management (Guernsey) Limited")) == [0, 0]
    assert not any("Auditor" in w for w in result["warnings"])


def test_llp_warnings_are_the_filings_own_inconsistencies_and_a_misread_dash():
    warnings = extract("epic_im_llp_group_2025")["warnings"]
    assert len(warnings) == 5
    turnover = next(w for w in warnings if w.startswith("Turnover"))
    assert "1,433,356" in turnover and "1,433,456" in turnover and "-100" in turnover
    assert any(w.startswith("Finance costs") and "+2" in w for w in warnings)
    # Accrued income shows "1" where the scan has a dash, so the LLP debtors do not add up.
    assert any(w.startswith("Debtors (2025-03-31_llp)") and "-1" in w for w in warnings)


# ------------------------------------------- the earlier layouts still read cleanly

@pytest.mark.parametrize("name", ["11508952_aa_2025-09-23", "companies_house_document"])
def test_the_small_company_and_shell_filings_have_no_warnings(name):
    assert extract(name)["warnings"] == []


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
    rows = read_rows([text_row("TOTAL ASSETS LESS CURRENT"), text_row("LIABILITIES  1,835,176  2,321,369")])
    assert [r["label"] for r in rows] == ["TOTAL ASSETS LESS CURRENT LIABILITIES"]
    assert rows[0]["values"] == [1835176, 2321369]


def test_short_line_finishing_the_label_above_is_joined():
    rows = read_rows([text_row("SURPLUS / (DEFICIT) ON"), text_row("ORDINARY ACTIVITIES  3  64,364  (356,072)"),
                      text_row("BEFORE TAXATION")])
    assert [r["label"] for r in rows] == ["SURPLUS / (DEFICIT) ON ORDINARY ACTIVITIES BEFORE TAXATION"]


def test_headings_ending_in_a_colon_or_a_noun_are_not_joined_to_the_next_row():
    assert len(read_rows([text_row("Represented by:"), text_row("Revenue Reserves  1,776,018  1,746,349")])) == 2
    # "amount" is not a word that continues a label
    assert len(read_rows([text_row("Carrying amount"), text_row("At 31 August 2025  100  200")])) == 2


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
