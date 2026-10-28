"""The filing pipeline (accounts.py) and the bucket helpers (ionos.py), with fakes for the network and database."""

import pytest

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


def test_object_keys_have_no_leading_slash():
    assert ionos.object_keys(42) == ("accounts/pdf/42.pdf", "accounts/txt/42.txt")


def test_make_client_needs_both_keys(monkeypatch):
    monkeypatch.delenv(ionos.ACCESS_KEY_VAR, raising=False)
    monkeypatch.setenv(ionos.SECRET_KEY_VAR, "x")
    with pytest.raises(RuntimeError, match="IONOS_BUCKET_ACCESS_KEY"):
        ionos.make_client()


def test_process_filing_uploads_both_files_then_records(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "download_pdf", lambda url, path: path.write_bytes(b"%PDF-1.4"))
    monkeypatch.setattr(accounts, "ocr_to_text", lambda pdf, txt, cache, dpi: txt.write_text("PAGE 1\nhello"))
    client, connection = FakeClient(), FakeConnection()

    accounts.process_filing(7, "https://example.test/a.pdf", tmp_path, client, connection)

    assert [key for _, key, _ in client.uploads] == ["accounts/pdf/7.pdf", "accounts/txt/7.txt"]
    assert connection.executed == [(accounts.INSERT_RECORD, (7, "accounts/txt/7.txt"))] and connection.commits == 1


def test_failed_upload_leaves_no_record(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "download_pdf", lambda url, path: path.write_bytes(b"%PDF-1.4"))
    monkeypatch.setattr(accounts, "ocr_to_text", lambda pdf, txt, cache, dpi: txt.write_text("x"))
    client, connection = FakeClient(), FakeConnection()
    client.upload_file = lambda *a, **k: (_ for _ in ()).throw(OSError("network down"))

    with pytest.raises(OSError):
        accounts.process_filing(7, "https://example.test/a.pdf", tmp_path, client, connection)
    assert connection.executed == []


def test_pending_query_asks_for_unsaved_accounts_filings_only():
    assert "cha.id IS NULL" in database.PENDING_FILINGS and "LIMIT %s" in database.PENDING_FILINGS
    assert database.PENDING_FILINGS.count("%s") == len(database.ACCOUNT_TYPES) + 1


def test_connect_explains_a_missing_setting(monkeypatch):
    monkeypatch.delenv(database.CONNSTR_VAR, raising=False)
    with pytest.raises(RuntimeError, match="RPP2_CONNSTR"):
        database.connect()
