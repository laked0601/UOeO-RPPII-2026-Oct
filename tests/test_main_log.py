"""
Tests for the results log (pipeline.py) and the --log option of main.py (log entries and the --log option).
"""

from datetime import datetime

import pytest

import main
from extract_data.pipeline import append_log, failure_entry, result_entry

NOW = datetime(2026, 10, 27, 14, 3, 9)
PARSED = {"statements": [{}, {}], "note_tables": [{}],
          "company": {"registration_number": "04366849", "period_end": "2025-12-31",
                      "currency": "USD", "unit_multiplier": 1_000_000},
          "warnings": ["Balance sheet (2025): 'Total assets' is 5 but the rows above do not add up to it."]}


def test_entry_shows_company_counts_and_every_warning():
    entry = result_entry("shell.pdf", PARSED, [{}] * 40, now=NOW)
    assert entry.startswith("2026-10-27 14:03:09  shell.pdf\n")
    assert "company number : 04366849" in entry
    assert "period end     : 2025-12-31" in entry
    assert "extracted      : 3 tables, 40 figures" in entry
    assert "warnings       : 1" in entry and "    - Balance sheet (2025)" in entry


def test_entry_without_warnings_or_details_says_so():
    entry = result_entry("x.pdf", {"company": {}, "warnings": []}, [], now=NOW)
    assert "(none)" in entry and "company number : not found" in entry


def test_failure_entry_names_the_error():
    entry = failure_entry("bad.pdf", ValueError("no pages"), now=NOW)
    assert "FAILED         : ValueError: no pages" in entry


def test_entries_are_appended(tmp_path):
    log = tmp_path / "log.txt"
    append_log(log, "one\n")
    append_log(log, "two\n")
    assert log.read_text(encoding="utf-8") == "one\ntwo\n"


def test_main_logs_each_pdf_and_each_failure(tmp_path, monkeypatch):
    for name in ("a.pdf", "b.pdf"):
        (tmp_path / name).write_bytes(b"")

    def fake_process(pdf, *args, **kwargs):
        if pdf.name == "b.pdf":
            raise RuntimeError("cannot read")
        return tmp_path / "a.json", PARSED, [{}] * 3

    monkeypatch.setattr(main, "process_pdf", fake_process)
    out = tmp_path / "out"
    with pytest.raises(SystemExit):  # exits with an error because b.pdf failed
        main.main([str(tmp_path), "--out", str(out)])
    log = (out / "extract_log.txt").read_text(encoding="utf-8")
    assert "a.pdf" in log and "3 figures" in log
    assert "b.pdf" in log and "FAILED         : RuntimeError: cannot read" in log


def test_log_file_can_be_chosen(tmp_path, monkeypatch):
    (tmp_path / "a.pdf").write_bytes(b"")
    monkeypatch.setattr(main, "process_pdf", lambda pdf, *a, **k: (tmp_path / "a.json", PARSED, []))
    chosen = tmp_path / "mine.txt"
    main.main([str(tmp_path / "a.pdf"), "--out", str(tmp_path / "out"), "--log", str(chosen)])
    assert chosen.exists() and not (tmp_path / "out" / "extract_log.txt").exists()


def test_assumed_currency_is_flagged_in_the_log():
    company = {"currency": "GBP", "unit_multiplier": 1, "currency_assumed": True}
    entry = result_entry("x.pdf", {"company": company, "warnings": []}, [], now=NOW)
    assert "GBP x1  (ASSUMED: no currency found in the document)" in entry
    company["currency_assumed"] = False
    assert "ASSUMED" not in result_entry("x.pdf", {"company": company, "warnings": []}, [], now=NOW)
