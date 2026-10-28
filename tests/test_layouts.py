"""
Tests for extract_data.parsing.document on filings with different layouts.

Each fixture in tests/fixtures/*.ocr.json is the saved OCR output (with the
horizontal position of every fragment) of one real filing:
  * crown_overseas_abbreviated_2015   abbreviated accounts, "Notes  2015  2014" header
  * 05421996_aa_2026-05-26            small company accounts, tables running over a page
  * epic_im_llp_group_2025            group LLP accounts: Consolidated and LLP columns,
                                      five-column member statements, blank cells everywhere
                                      (prose pages are blanked in the fixture to keep it small)
  * 11508952_aa_2025-09-23, companies_house_document   the two layouts from test_generic.py

Warnings that these tests expect for the LLP filing are genuine: the scan itself
contains inconsistent totals, or the OCR misread a dash as "1".
"""

import json
from pathlib import Path

import pytest

from extract_data.parsing.document import extract_document
from extract_data.parsing.figures import is_year_row
from extract_data.parsing.labels import standard_label
from extract_data.parsing.rows import TRAILING_NUMBERS, read_rows
from extract_data.parsing.tables import STATEMENT_HEADING
from rowtext import text_row

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


# --------------------------------------------------------------- helpers


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
