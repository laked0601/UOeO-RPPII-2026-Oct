"""
Tests for extract_data.standardise: every filing under the same fixed headings.

Uses the saved OCR fixtures (see test_layouts.py).  Currency is not asserted for
the LLP filing because its fixture leaves out the prose pages that mention sterling.
"""

import json
import main
import pytest
import shutil
from extract_data.parsing.document import extract_document
from extract_data.results.standardise import SCHEMA, entity_of, standardise
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["11508952_aa_2025-09-23", "companies_house_document", "05421996_aa_2026-05-26",
         "crown_overseas_abbreviated_2015", "epic_im_llp_group_2025"]


def load(name):
    pages = json.loads((FIXTURES / f"{name}.ocr.json").read_text(encoding="utf-8"))
    return extract_document(pages, f"{name}.pdf")


def standard(name):
    return standardise(load(name))


def period(result, entity, iso):
    return result["entities"][entity]["periods"][iso]


# ---------------------------------------------------------------- schema


def test_headings_are_unique_across_groups():
    fields = [f for fields in SCHEMA.values() for f in fields]
    assert len(fields) == len(set(fields))


@pytest.mark.parametrize("name", NAMES)
def test_every_filing_has_exactly_the_same_headings(name):
    result = standard(name)
    assert result["schema_version"] == 1
    assert result["entities"]
    for entity in result["entities"].values():
        for block in entity["periods"].values():
            assert list(block) == ["status", *SCHEMA]
            for group, fields in SCHEMA.items():
                assert list(block[group]) == fields  # same names, same order, none missing


@pytest.mark.parametrize("name", NAMES)
def test_periods_are_listed_newest_first_and_json_safe(name):
    result = standard(name)
    for entity in result["entities"].values():
        dates = list(entity["periods"])
        assert dates == sorted(dates, reverse=True)
    json.dumps(result)


def test_entity_detection():
    assert entity_of("Consolidated statement of financial position") == "group"
    assert entity_of("LLP statement of financial position") == "company"
    assert entity_of("Balance sheet") is None


# -------------------------------------------------- small company (2025)


def test_small_company_headings_for_both_years():
    result = standard("11508952_aa_2025-09-23")
    assert list(result["entities"]) == ["company"]
    now, before = period(result, "company", "2025-08-31"), period(result, "company", "2024-08-31")
    assert now["assets"]["tangible_assets"] == 773374 and before["assets"]["tangible_assets"] == 773587
    assert now["assets"]["cash"] == 25350
    assert now["creditors"]["creditors_within_one_year"] == -344458  # sign as printed (brackets)
    assert now["creditors"]["creditors_after_one_year"] == -433940
    assert now["net_assets"] == {"net_current_assets": -319108,
                                 "total_assets_less_current_liabilities": 454266, "net_assets": 20326}
    assert now["capital_and_reserves"]["share_capital"] == 2
    assert now["capital_and_reserves"]["retained_earnings"] == 20324
    assert now["capital_and_reserves"]["total_equity"] == 20326


def test_missing_figures_are_null_not_absent():
    now = period(standard("11508952_aa_2025-09-23"), "company", "2025-08-31")
    assert now["income"]["turnover"] is None  # this filing has no P&L
    assert now["costs"]["cost_of_sales"] is None
    assert now["assets"]["stocks"] is None
    assert now["profit_and_loss"]["profit_for_period"] is None


def test_depreciation_comes_from_the_tangible_assets_note():
    result = standard("11508952_aa_2025-09-23")
    now, before = period(result, "company", "2025-08-31"), period(result, "company", "2024-08-31")
    assert now["depreciation"] == {"tangible_cost": 774363, "depreciation_charge": 213,
                                   "accumulated_depreciation": 989, "net_book_value": 773374}
    # "At 1 September 2024" is the end of the previous period; one cost row names both dates.
    assert before["depreciation"]["tangible_cost"] == 774363
    assert before["depreciation"]["accumulated_depreciation"] == 776
    assert before["depreciation"]["depreciation_charge"] is None
    assert now["other"]["average_employees"] == before["other"]["average_employees"] == 1


# --------------------------------------------------------- other filings


def test_interim_accounts_in_us_dollars():
    result = standard("companies_house_document")
    assert (result["currency"], result["unit_multiplier"]) == ("USD", 1_000_000)
    now = period(result, "company", "2025-12-31")
    assert now["status"] == "Unaudited" and period(result, "company", "2024-12-31")["status"] == "Audited"
    assert now["assets"]["fixed_assets"] == 257542  # the unlabelled subtotal under "Non-current assets"
    assert now["assets"]["current_assets"] == 9541
    assert now["assets"]["total_assets"] == 267083
    assert now["income"] == {"turnover": None, "other_operating_income": None,
                             "dividend_income": 23999, "interest_receivable": 263}
    assert now["profit_and_loss"]["profit_for_period"] == 23886
    assert now["profit_and_loss"]["dividends_paid"] == -8472
    assert now["capital_and_reserves"]["total_equity_and_liabilities"] == 267083


def test_figures_taken_as_nil_are_reported():
    result = standard("companies_house_document")
    assert period(result, "company", "2025-12-31")["assets"]["cash"] == 0
    assert {"entity": "company", "period_end": "2025-12-31", "heading": "assets.cash",
            "reason": "nil_assumed"} in result["inferred"]


def test_rows_without_a_heading_are_listed_not_dropped():
    unmapped = {(u["statement"], u["label"]) for u in standard("companies_house_document")["unmapped"]}
    assert ("Balance sheet", "Deferred tax asset") in unmapped


def test_abbreviated_accounts_reserves_and_losses():
    result = standard("crown_overseas_abbreviated_2015")
    now = period(result, "company", "2015-04-30")
    assert now["capital_and_reserves"]["revaluation_reserve"] == 40919
    assert now["capital_and_reserves"]["retained_earnings"] == -13392  # a loss is negative
    assert now["depreciation"]["depreciation_charge"] == 3407


def test_small_accounts_provisions_and_lone_employee_figure():
    result = standard("05421996_aa_2026-05-26")
    now, before = period(result, "company", "2026-04-30"), period(result, "company", "2025-04-30")
    assert now["creditors"]["provisions"] == -13381
    assert now["assets"]["current_assets"] == 728736
    assert before["other"]["average_employees"] == 4
    assert now["other"]["average_employees"] is None  # the OCR found only one "4"
    assert now["depreciation"]["tangible_cost"] == 209142 and before["depreciation"]["tangible_cost"] == 191931


# ------------------------------------------------- group LLP accounts


def test_group_and_company_are_kept_apart():
    result = standard("epic_im_llp_group_2025")
    assert list(result["entities"]) == ["group", "company"]
    group, company = period(result, "group", "2025-03-31"), period(result, "company", "2025-03-31")
    assert group["income"]["turnover"] == 1433456 and company["income"]["turnover"] is None
    assert group["assets"]["debtors"] == 451106 and company["assets"]["debtors"] == 112447
    assert group["net_assets"]["net_assets"] == -617740 and company["net_assets"]["net_assets"] == 127559


def test_group_income_costs_and_losses():
    group = period(standard("epic_im_llp_group_2025"), "group", "2025-03-31")
    assert group["costs"] == {"cost_of_sales": -213135, "administrative_expenses": -1808525,
                              "interest_payable": -6833}
    assert group["profit_and_loss"]["operating_profit"] == -588204
    assert group["profit_and_loss"]["profit_for_period"] == -499290  # the loss, from the long label
    assert group["income"]["interest_receivable"] == 95747


def test_llp_specific_headings():
    result = standard("epic_im_llp_group_2025")
    group = period(result, "group", "2025-03-31")["capital_and_reserves"]
    assert group["members_capital"] == 1701003 and group["non_controlling_interests"] == 426
    assert group["loans_due_to_members"] == -1729006  # "Other amounts" under the members heading
    company = period(result, "company", "2025-03-31")["capital_and_reserves"]
    assert company["loans_due_to_members"] == -633907  # heading wrapped over two lines


def test_notes_follow_the_group_when_there_is_one():
    group = period(standard("epic_im_llp_group_2025"), "group", "2025-03-31")
    assert group["depreciation"] == {"tangible_cost": 89024, "depreciation_charge": 12690,
                                     "accumulated_depreciation": 81126, "net_book_value": 7898}


# ----------------------------------------------------------- conflicts


def test_a_heading_found_twice_with_different_values_is_reported_and_the_first_kept():
    column = {"key": "2025-01-31", "label": "2025", "period_end": "2025-01-31", "status": None}

    def statement(name, value):
        return {"kind": "statement", "name": name, "note_number": None, "page": 1, "columns": [column],
                "rows": [{"section": "", "label": "Turnover", "note": None, "kind": "line",
                          "standard": "turnover", "values": {"2025-01-31": value}}]}

    result = {"company": {"period_end": "2025-01-31"},
              "statements": [statement("Income statement", 100), statement("Income statement (continued)", 250)],
              "note_tables": []}
    out = standardise(result)
    assert period(out, "company", "2025-01-31")["income"]["turnover"] == 100
    assert out["conflicts"] == [{"entity": "company", "period_end": "2025-01-31", "heading": "income.turnover",
                                 "kept": 100, "ignored": 250, "source": "Income statement (continued) / Turnover"}]


# ------------------------------------------- end to end through main.py


def test_main_writes_the_standard_file_without_running_ocr(tmp_path):
    name = "crown_overseas_abbreviated_2015"
    shutil.copy(FIXTURES / f"{name}.ocr.json", tmp_path / f"{name}.ocr.json")  # the OCR cache
    pdf = tmp_path / f"{name}.pdf"
    pdf.write_bytes(b"")  # never opened: the cache is used

    json_path, parsed, facts = main.process_pdf(pdf, tmp_path, 300, True)

    standard_file = json.loads((tmp_path / f"{name}.standard.json").read_text(encoding="utf-8"))
    assert standard_file["company_number"] == "NI019095"
    assert standard_file["period_end"] == "2015-04-30"
    assert standard_file["entities"]["company"]["periods"]["2015-04-30"]["capital_and_reserves"][
               "total_equity"] == 37527
    assert parsed["standardised"]["entities"] == standard_file["entities"]  # also inside the main JSON
    assert json.loads(json_path.read_text(encoding="utf-8"))["standardised"]["schema_version"] == 1
    assert (tmp_path / f"{name}.facts.csv").exists() and facts
