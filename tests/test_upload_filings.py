"""Tests for a whole run of upload_filings.py: its log file and its exit status."""

import pytest

import upload_filings


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
    assert "[3/3] saved filing 3" in capsys.readouterr().out        # and it was shown on the screen as well


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
