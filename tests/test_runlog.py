"""Tests for the progress lines, the time estimate and the log names in extract_data.runlog."""

from datetime import datetime

from extract_data import runlog

NOW = datetime(2026, 10, 28, 14, 0, 0)


def test_durations_are_easy_to_read():
    assert runlog.format_duration(8.44) == "8.4s"
    assert runlog.format_duration(125) == "2m 05s"
    assert runlog.format_duration(3720) == "1h 02m"


def test_a_saved_filing_shows_its_place_the_time_it_took_and_the_time_so_far():
    line = runlog.progress_line(12, 50, 172, None, 8.4, 102)
    assert line == "[12/50] saved filing 172  (took 8.4s, 1m 42s so far)"


def test_a_failed_filing_and_a_dry_run_are_worded_differently():
    assert "FAILED filing 9: cannot read" in runlog.progress_line(1, 3, 9, ValueError("cannot read"), 1, 1)
    assert "checked filing 9" in runlog.progress_line(1, 3, 9, None, 1, 1, dry_run=True)


def test_the_estimate_waits_for_a_few_filings_and_uses_the_recent_average():
    assert runlog.estimate_remaining([8.0, 9.0], 40) is None  # too early
    assert runlog.estimate_remaining([8.0, 9.0, 10.0], 40) == 360.0  # 9s x 40
    assert runlog.estimate_remaining([8.0, 9.0, 10.0], 0) is None  # nothing left


def test_the_estimate_shows_the_time_left_and_when_it_should_finish():
    line = runlog.progress_line(10, 50, 172, None, 9.0, 90, left=360, now=NOW)
    assert line.endswith("1m 30s so far, about 6m 00s left, done around 14:06)")


def test_log_names_give_the_start_time_and_the_number_of_filings():
    assert runlog.log_name(NOW) == "2026-10-28_14-00-00_running.txt"
    assert runlog.log_name(NOW, 50) == "2026-10-28_14-00-00_50-filings.txt"
    assert runlog.log_name(NOW, 50, 2) == "2026-10-28_14-00-00_50-filings_2-failed.txt"
