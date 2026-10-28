"""The filing pipeline (accounts.py) and the bucket helpers (ionos.py), with fakes for the network and database."""

from urllib.error import HTTPError, URLError

import pytest
from mysql.connector import IntegrityError, errorcode

from extract_data.storage import accounts, database, ionos


class FakeClient:
    def __init__(self):
        self.uploads = []

    def upload_file(self, path, bucket, key, ExtraArgs):
        self.uploads.append((bucket, key, ExtraArgs["ContentType"]))


class FakeConnection:
    def __init__(self):
        self.executed, self.commits = [], 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def commit(self):
        self.commits += 1

    def ping(self, reconnect, attempts, delay):
        self.pings = getattr(self, "pings", []) + [(reconnect, attempts)]

    def rollback(self):
        self.rollbacks = getattr(self, "rollbacks", 0) + 1


class DuplicateConnection(FakeConnection):
    """A database where the filing already has a row."""

    def __init__(self, error):
        super().__init__()
        self.error = error

    def execute(self, sql, params):
        raise self.error


def test_the_connection_is_checked_and_reopened_if_dropped_before_each_row():
    connection = FakeConnection()
    accounts.record_filing(connection, 7)
    accounts.record_filing(connection, 8)
    assert connection.pings == [(True, accounts.RECONNECT_TRIES)] * 2
    assert connection.commits == 2


def test_a_filing_that_already_has_a_row_counts_as_recorded():
    connection = DuplicateConnection(IntegrityError("Duplicate entry", errno=errorcode.ER_DUP_ENTRY))
    accounts.record_filing(connection, 7)
    assert connection.commits == 0 and connection.rollbacks == 1


def test_any_other_database_error_is_still_an_error():
    connection = DuplicateConnection(IntegrityError("Cannot add a child row", errno=errorcode.ER_NO_REFERENCED_ROW_2))
    with pytest.raises(IntegrityError):
        accounts.record_filing(connection, 7)


def test_object_keys_have_no_leading_slash():
    assert ionos.object_keys(42) == ("accounts/pdf/42.pdf", "accounts/txt/42.txt")


def test_make_client_needs_both_keys(monkeypatch):
    monkeypatch.delenv(ionos.ACCESS_KEY_VAR, raising=False)
    monkeypatch.setenv(ionos.SECRET_KEY_VAR, "x")
    with pytest.raises(RuntimeError, match="IONOS_BUCKET_ACCESS_KEY"):
        ionos.make_client()


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.data


def fake_network(monkeypatch, outcomes):
    """Make urlopen give (or raise) each of `outcomes` in turn; returns the list of waits made."""
    waits, outcomes = [], iter(outcomes)

    def urlopen(request, timeout):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(accounts, "urlopen", urlopen)
    monkeypatch.setattr(accounts.time, "sleep", waits.append)
    return waits


def test_a_download_is_tried_again_after_a_network_problem(tmp_path, monkeypatch):
    waits = fake_network(monkeypatch, [URLError("reset"), HTTPError("u", 503, "busy", {}, None), b"%PDF-1.4 ok"])
    accounts.download_pdf("/a.pdf", tmp_path / "a.pdf")
    assert (tmp_path / "a.pdf").read_bytes() == b"%PDF-1.4 ok"
    assert waits == [accounts.RETRY_WAIT, accounts.RETRY_WAIT * 2]


def test_a_download_gives_up_after_the_last_try(tmp_path, monkeypatch):
    fake_network(monkeypatch, [URLError("down")] * accounts.DOWNLOAD_TRIES)
    with pytest.raises(URLError):
        accounts.download_pdf("/a.pdf", tmp_path / "a.pdf")


def test_a_missing_file_is_not_tried_again(tmp_path, monkeypatch):
    waits = fake_network(monkeypatch, [HTTPError("u", 404, "not found", {}, None)])
    with pytest.raises(HTTPError):
        accounts.download_pdf("/a.pdf", tmp_path / "a.pdf")
    assert waits == []


def test_something_that_is_not_a_pdf_is_refused(tmp_path, monkeypatch):
    fake_network(monkeypatch, [b"<html>busy</html>"])
    with pytest.raises(ValueError):
        accounts.download_pdf("/a.pdf", tmp_path / "a.pdf")
    assert not (tmp_path / "a.pdf").exists()


def patch_steps(monkeypatch):
    monkeypatch.setattr(accounts, "download_pdf", lambda url, path: path.write_bytes(b"%PDF-1.4"))
    monkeypatch.setattr(accounts, "ocr_to_text", lambda pdf, txt, cache, dpi: txt.write_text("PAGE 1\nhello"))


def test_filings_are_uploaded_then_recorded(tmp_path, monkeypatch):
    patch_steps(monkeypatch)
    client, connection = FakeClient(), FakeConnection()

    results = list(accounts.save_filings([(7, "https://example.test/a.pdf")], tmp_path, client, connection))

    assert results == [(7, None)]
    assert sorted(key for _, key, _ in client.uploads) == ["accounts/pdf/7.pdf", "accounts/txt/7.txt"]
    assert connection.executed == [(accounts.INSERT_RECORD, (7,))] and connection.commits == 1


def test_a_failed_upload_leaves_no_record_and_the_others_carry_on(tmp_path, monkeypatch):
    patch_steps(monkeypatch)
    client, connection = FakeClient(), FakeConnection()
    real_upload = client.upload_file

    def upload(path, bucket, key, ExtraArgs):
        if key.endswith("/8.pdf"):
            raise OSError("network down")
        real_upload(path, bucket, key, ExtraArgs)

    client.upload_file = upload
    filings = [(7, "u"), (8, "u"), (9, "u")]

    results = dict(accounts.save_filings(filings, tmp_path, client, connection))

    assert results[7] is None and results[9] is None and isinstance(results[8], OSError)
    assert sorted(params for _, params in connection.executed) == [(7,), (9,)]


def test_a_failed_download_is_reported_and_not_uploaded(tmp_path, monkeypatch):
    patch_steps(monkeypatch)

    def download(url, path):
        raise ValueError("did not return a PDF")

    monkeypatch.setattr(accounts, "download_pdf", download)
    client, connection = FakeClient(), FakeConnection()

    results = list(accounts.save_filings([(7, "u")], tmp_path, client, connection))

    assert isinstance(results[0][1], ValueError) and client.uploads == [] and connection.executed == []


def test_dry_run_downloads_and_reads_but_uploads_and_records_nothing(tmp_path, monkeypatch):
    patch_steps(monkeypatch)
    client, connection = FakeClient(), FakeConnection()

    results = list(accounts.save_filings([(7, "u")], tmp_path, client, connection, dry_run=True))

    assert results == [(7, None)] and (tmp_path / "7.txt").exists()
    assert client.uploads == [] and connection.executed == []


def test_the_next_downloads_start_while_a_filing_is_being_read(tmp_path, monkeypatch):
    """The OCR of the first filing must find the others already requested."""
    started = []

    def download(url, path):
        started.append(path.stem)
        path.write_bytes(b"%PDF")

    seen_at_first_ocr = []

    def ocr(pdf, txt, cache, dpi):
        seen_at_first_ocr.append(len(started))
        txt.write_text("x")

    monkeypatch.setattr(accounts, "download_pdf", download)
    monkeypatch.setattr(accounts, "ocr_to_text", ocr)
    filings = [(n, "u") for n in range(1, 6)]
    list(accounts.save_filings(filings, tmp_path, FakeClient(), FakeConnection()))
    assert sorted(started) == ["1", "2", "3", "4", "5"]
    assert seen_at_first_ocr[0] >= 2


def test_pending_query_asks_for_unsaved_accounts_filings_only():
    query = database.build_query()
    assert "cha.id IS NULL" in query and "LIMIT %s" in query and "document_page_count" in query
    assert query.count("%s") == len(database.ACCOUNT_TYPES) + 2  # types, fewest pages, limit
    assert "ORDER BY fh.id" in query and "`date`" not in query


def test_pending_query_can_start_at_a_year_and_run_newest_first():
    query = database.build_query(since_year=2020, newest_first=True)
    assert "fh.`date` >= %s" in query and "fh.`date` IS NULL" in query  # a filing with no date is kept
    assert "ORDER BY fh.`date` DESC, fh.id DESC" in query
    assert query.count("%s") == len(database.ACCOUNT_TYPES) + 3  # types, fewest pages, date, limit


class QueryConnection:
    def __init__(self):
        self.sql = self.params = None

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return [(1, "u")]

    def close(self):
        pass


def test_a_run_takes_at_most_the_maximum_whatever_the_limit():
    connection = QueryConnection()
    database.pending_filings(connection)  # no limit given
    assert connection.params[-1] == database.MAX_PER_RUN == 100000
    database.pending_filings(connection, 5_000_000)  # more than allowed
    assert connection.params[-1] == database.MAX_PER_RUN
    database.pending_filings(connection, 250)  # fewer is kept
    assert connection.params[-1] == 250
    assert connection.sql.count("%s") == len(connection.params)


def test_the_year_becomes_the_first_of_january_in_the_parameters():
    connection = QueryConnection()
    assert database.pending_filings(connection, 50, 2, since_year=2020, newest_first=True) == [(1, "u")]
    assert connection.params == (*database.ACCOUNT_TYPES, 2, "2020-01-01", 50)
    assert connection.sql.count("%s") == len(connection.params)
    database.pending_filings(connection, 5)
    assert connection.params == (*database.ACCOUNT_TYPES, 2, 5)


def test_connect_explains_a_missing_setting(monkeypatch):
    monkeypatch.delenv(database.CONNSTR_VAR, raising=False)
    with pytest.raises(RuntimeError, match="RPP2_CONNSTR"):
        database.connect()
