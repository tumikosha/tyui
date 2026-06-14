"""Bookmarks storage: CRUD over a 0600 bookmarks.json."""

import json
import os
import stat

from dunders.config.bookmarks import (
    add_bookmark,
    bookmarks_path,
    list_bookmarks,
    remove_bookmark,
)


def test_empty_when_missing():
    assert list_bookmarks() == []


def test_add_then_list_round_trip():
    assert add_bookmark("home", "file:///home/u", None)
    assert add_bookmark("srv", "sftp://u@h:22!/var", "pw")
    items = list_bookmarks()
    assert [b["label"] for b in items] == ["home", "srv"]
    assert items[0]["uri"] == "file:///home/u"
    assert items[0]["password"] is None
    assert items[1]["password"] == "pw"


def test_file_is_0600():
    add_bookmark("x", "file:///x", None)
    mode = stat.S_IMODE(os.stat(bookmarks_path()).st_mode)
    assert mode == 0o600


def test_remove_by_index():
    add_bookmark("a", "file:///a", None)
    add_bookmark("b", "file:///b", None)
    assert remove_bookmark(0)
    assert [b["label"] for b in list_bookmarks()] == ["b"]
    assert remove_bookmark(5) is False  # out of range


def test_corrupt_file_reads_empty(tmp_path, monkeypatch):
    bookmarks_path().parent.mkdir(parents=True, exist_ok=True)
    bookmarks_path().write_text("{ not json")
    assert list_bookmarks() == []


def test_non_dict_entries_filtered(tmp_path):
    bookmarks_path().parent.mkdir(parents=True, exist_ok=True)
    bookmarks_path().write_text(json.dumps({"bookmarks": ["bad", {"uri": "file:///ok", "label": "ok"}]}))
    assert [b["uri"] for b in list_bookmarks()] == ["file:///ok"]
