"""
Tests for upload_filings.py: the progress lines and log names (extract_data.runlog), and a whole run with its
log file and exit status.
"""

from datetime import datetime

import pytest

import upload_filings
from extract_data import runlog


class FakeConnection:
    def close(self):
        pass


def fake_run(monkeypatch, results, ionos_ready=True):
    monkeypatch.setattr(upload_filings.ionos, "make_client", lambda: object())
    monkeypatch.setattr(upload_filings.database, "connect", lambda: FakeConnection())
    monkeypatch.setattr(upload_filings.database, "pending_filings",
                        lambda *args, **kwargs: [(i, "u") for i, _ in results])
    monkeypatch.setattr(upload_filings, "save_filings", lambda *args, **kwargs: iter(results))


def test_the_log_is_named_by_the_filings_handled_and_holds_what_was_printed(tmp_path, monkeypatch, capsys):
    fake_run(monkeypatch, [(1, None), (2, None), (3, None)])
    upload_filings.main(["--log-dir", str(tmp_path)])
    [log] = list(tmp_path.iterdir())
    assert log.name.endswith("_3-filings.txt") and "running" not in log.name
    text = log.read_text(encoding="utf-8")
    assert "3 filing(s) to save" in text and "[3/3] saved filing 3" in text and "Finished 3 filing(s)" in text
    assert "[3/3] saved filing 3" in capsys.readouterr().out  # and it was shown on the screen as well


def test_a_run_with_failures_is_named_for_them_and_still_exits_with_an_error(tmp_path, monkeypatch):
    fake_run(monkeypatch, [(1, None), (2, ValueError("bad"))])
    with pytest.raises(SystemExit):
        upload_filings.main(["--log-dir", str(tmp_path)])
    [log] = list(tmp_path.iterdir())
    assert log.name.endswith("_2-filings_1-failed.txt")


def test_a_stopped_run_still_leaves_a_named_log(tmp_path, monkeypatch):
    def interrupted(*args, **kwargs):
        yield 1, None
        raise KeyboardInterrupt

    fake_run(monkeypatch, [(1, None), (2, None)])
    monkeypatch.setattr(upload_filings, "save_filings", interrupted)
    with pytest.raises(KeyboardInterrupt):
        upload_filings.main(["--log-dir", str(tmp_path)])
    [log] = list(tmp_path.iterdir())
    assert log.name.endswith("_1-filings.txt")


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


def test_a_long_list_of_failures_is_cut_short_in_the_exit_message(tmp_path, monkeypatch):
    fake_run(monkeypatch, [(n, ValueError("bad")) for n in range(1, 26)])
    with pytest.raises(SystemExit) as stopped:
        upload_filings.main(["--log-dir", str(tmp_path)])
    message = str(stopped.value)
    assert message.startswith("25 filing(s) failed") and message.endswith("20 ...") and "21" not in message
