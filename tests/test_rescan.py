"""
Tests for re-reading pages whose totals do not add up (extract_data.rescan).

The page reader is replaced by a fake that returns prepared rows, so no OCR runs.
"""

import json

from extract_data.rescan import load_tried, rescan_flagged_pages, tried_path

BAD = ["Acme Limited", "BALANCE SHEET", "2025  2024", "Fixed assets  100  90", "Current assets  50  40",
       "Total assets  151  130"]  # 151 is a misread 150
GOOD = [line.replace("151", "150") for line in BAD]
TITLE = ["Acme Limited", "Annual report"]


def pages(page_two):
    return [TITLE, page_two]


class FakeRescan:
    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def __call__(self, numbers):
        self.asked.append(list(numbers))
        return {n: self.rows for n in numbers if self.rows is not None}


def test_a_better_reading_of_the_flagged_page_is_kept():
    rescan = FakeRescan(GOOD)
    kept, result, rescanned, improved = rescan_flagged_pages(pages(BAD), "x.pdf", rescan)
    assert rescan.asked == [[2]]  # only the page with the warning
    assert (rescanned, improved) == ([2], [2])
    assert kept[1] == GOOD
    assert not any("Total assets" in w for w in result["warnings"])


def test_a_reading_that_does_not_help_is_discarded():
    rescan = FakeRescan(BAD)  # the filing itself is wrong: same result again
    kept, result, rescanned, improved = rescan_flagged_pages(pages(BAD), "x.pdf", rescan)
    assert rescanned == [2] and improved == []
    assert kept[1] == BAD
    assert any("Total assets" in w for w in result["warnings"])


def test_pages_already_tried_are_not_read_again():
    rescan = FakeRescan(GOOD)
    kept, _, rescanned, _ = rescan_flagged_pages(pages(BAD), "x.pdf", rescan, tried={2})
    assert rescan.asked == [] and rescanned == [] and kept[1] == BAD


def test_clean_filing_is_not_rescanned():
    rescan = FakeRescan(GOOD)
    _, _, rescanned, _ = rescan_flagged_pages(pages(GOOD), "x.pdf", rescan)
    assert rescan.asked == [] and rescanned == []


def test_page_the_rescan_skips_is_left_alone():
    rescan = FakeRescan(None)  # e.g. the page has a text layer
    kept, _, rescanned, improved = rescan_flagged_pages(pages(BAD), "x.pdf", rescan)
    assert rescanned == [2] and improved == [] and kept[1] == BAD


def test_remembered_pages_round_trip(tmp_path):
    path = tried_path("a/b/file.pdf", tmp_path)
    assert path.name == "file.rescan.json" and load_tried(path) == set()
    path.write_text(json.dumps({"dpi": 450, "pages_tried": [3, 5]}), encoding="utf-8")
    assert load_tried(path) == {3, 5}
    path.write_text("not json", encoding="utf-8")
    assert load_tried(path) == set()


def test_pages_tried_at_a_lower_dpi_are_tried_again(tmp_path):
    path = tmp_path / "a.rescan.json"
    path.write_text(json.dumps({"dpi": 450, "pages_tried": [3]}), encoding="utf-8")
    assert load_tried(path, 450) == {3}
    assert load_tried(path, 600) == set()


def test_saving_keeps_earlier_pages_at_the_same_dpi(tmp_path):
    from extract_data.rescan import save_tried
    path = tmp_path / "a.rescan.json"
    save_tried(path, 450, {3, 5})
    save_tried(path, 450, {9})
    assert load_tried(path, 450) == {3, 5, 9}
    save_tried(path, 600, {1})  # a new resolution starts a fresh record
    assert load_tried(path, 600) == {1}


def test_malformed_record_is_treated_as_empty(tmp_path):
    path = tmp_path / "a.rescan.json"
    path.write_text('{"pages_tried": [[1], [2]], "dpi": "x"}', encoding="utf-8")
    assert load_tried(path) == set()


def test_working_files_live_in_the_cache_folder_and_old_ones_are_moved(tmp_path):
    from extract_data.reading.ocr import cache_path
    (tmp_path / "file.ocr.json").write_text("[]", encoding="utf-8")  # left by an older version
    (tmp_path / "file.rescan.json").write_text('{"pages_tried": [4]}', encoding="utf-8")
    assert cache_path("file.pdf", tmp_path) == tmp_path / "cache" / "file.ocr.json"
    assert (tmp_path / "cache" / "file.ocr.json").read_text(encoding="utf-8") == "[]"
    assert not (tmp_path / "file.ocr.json").exists()
    assert load_tried(tried_path("file.pdf", tmp_path)) == {4}
    assert not (tmp_path / "file.rescan.json").exists()
