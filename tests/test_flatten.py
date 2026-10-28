"""
Tests for extract_data.flatten: the one-row-per-figure output for SQL.
"""

import csv
import json
import pytest
from extract_data.parsing.document import extract_document
from extract_data.results.flatten import FACT_COLUMNS, facts_flags, to_facts, write_facts
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NAMES = ["11508952_aa_2025-09-23", "companies_house_document", "05421996_aa_2026-05-26",
         "crown_overseas_abbreviated_2015", "epic_im_llp_group_2025"]


def extract(name):
    pages = json.loads((FIXTURES / f"{name}.ocr.json").read_text(encoding="utf-8"))
    return extract_document(pages, f"{name}.pdf")


def find(facts, **wanted):
    """The single fact whose fields equal `wanted`."""
    matches = [f for f in facts if all(f[k] == v for k, v in wanted.items())]
    assert len(matches) == 1, f"{len(matches)} facts match {wanted}"
    return matches[0]


def test_flags_keep_only_those_for_the_column():
    flags = ["no_figures_read", "nil_assumed:2025-03-31", "nil_assumed:2024-03-31"]
    assert facts_flags(flags, "2025-03-31") == "no_figures_read;nil_assumed"
    assert facts_flags(flags, "2023-03-31") == "no_figures_read"
    assert facts_flags(None, "2025-03-31") == ""


@pytest.mark.parametrize("name", NAMES)
def test_one_fact_per_figure_and_no_blank_values(name):
    result = extract(name)
    facts = to_facts(result)
    tables = result["statements"] + result["note_tables"]
    figures = sum(v is not None for t in tables for r in t["rows"] for v in r["values"].values())
    assert len(facts) == figures > 0
    assert all(f["value"] is not None for f in facts)
    assert all(set(f) == set(FACT_COLUMNS) for f in facts)


@pytest.mark.parametrize("name", NAMES)
def test_every_figure_has_a_unique_address(name):
    facts = to_facts(extract(name))
    addresses = [(f["source_file"], f["table_number"], f["row_number"], f["column_key"]) for f in facts]
    assert len(addresses) == len(set(addresses))


def test_a_figure_carries_its_company_table_row_and_column():
    facts = to_facts(extract("companies_house_document"))
    fact = find(facts, table_name="Balance sheet", label="Total equity", column_key="2025-12-31")
    assert fact["value"] == 265441
    assert fact["company_number"] == "04366849"
    assert fact["period_end"] == "2025-12-31"
    assert (fact["currency"], fact["unit_multiplier"]) == ("USD", 1_000_000)
    assert fact["standard_label"] == "total_equity"
    assert fact["row_kind"] == "total"
    assert fact["section"] == "Equity"
    assert fact["column_status"] == "Unaudited"
    assert fact["column_period_end"] == "2025-12-31"
    assert fact["table_kind"] == "statement"


def test_filing_details_come_from_the_file_name():
    fact = to_facts(extract("11508952_aa_2025-09-23"))[0]
    assert (fact["filing_type"], fact["filing_date"]) == ("aa", "2025-09-23")
    assert fact["company_number"] == "11508952"


def test_note_reference_and_nil_flag_are_kept():
    facts = to_facts(extract("companies_house_document"))
    assert find(facts, label="Investments in subsidiaries", column_key="2025-12-31")["row_note_ref"] == "2"
    cash = find(facts, label="Cash and cash equivalents", column_key="2025-12-31")
    assert cash["value"] == 0
    assert "nil_assumed" in cash["flags"].split(";")


def test_blank_cells_are_left_out():
    facts = to_facts(extract("epic_im_llp_group_2025"))
    debtors = [f for f in facts if f["table_name"] == "Debtors" and f["label"] == "Trade debtors"]
    assert sorted(f["column_key"] for f in debtors) == ["2024-03-31_consolidated", "2025-03-31_consolidated"]


def test_csv_round_trip(tmp_path):
    facts = to_facts(extract("epic_im_llp_group_2025"))
    csv_path = write_facts(facts, tmp_path, "epic")
    assert csv_path.name == "epic.facts.csv" and not (tmp_path / "epic.facts.json").exists()

    with open(csv_path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        assert reader.fieldnames == FACT_COLUMNS
    assert len(rows) == len(facts)
    assert [float(r["value"]) for r in rows] == [float(f["value"]) for f in facts]
    # Missing text fields are empty cells, which SQL imports can read as NULL.
    first_note = next(r for r in rows if r["table_name"] == "Debtors")
    assert first_note["table_note_number"] == "15" and first_note["section"] == ""
