"""Editing a member inside an archive: open_write(overwrite=True) replaces it,
and F4 opens an editable editor whose save writes back through the provider.
"""

import zipfile
from pathlib import Path

import pytest

from dunders.app import DundersApp
from dunders.core.vfs import VfsPath
from dunders.fm.file_panel import FilePanel
from dunders.fm.providers.sevenzip_provider import find_7z
from dunders.fm.providers.zip_provider import ZipProvider
from dunders.windowing import Desktop, Window
from dunders.windowing.editor import EditorContent

_needs_7z = pytest.mark.skipif(find_7z() is None, reason="no 7z binary on PATH")


def _make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.txt", b"original")
        zf.writestr("dir/b.txt", b"keep me")
    return path


class TestZipOverwrite:
    def test_overwrite_replaces_member_keeps_others(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        loc = VfsPath(scheme="zip", root=str(archive), parts=("a.txt",))
        with ZipProvider().open_write(loc, overwrite=True) as w:
            w.write(b"EDITED")
        with zipfile.ZipFile(archive) as zf:
            assert zf.read("a.txt") == b"EDITED"
            assert zf.read("dir/b.txt") == b"keep me"  # untouched
            # no duplicate entries
            assert zf.namelist().count("a.txt") == 1

    def test_default_still_refuses_existing(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        loc = VfsPath(scheme="zip", root=str(archive), parts=("a.txt",))
        with pytest.raises(OSError):
            ZipProvider().open_write(loc)  # overwrite=False


@_needs_7z
class TestSevenZipOverwrite:
    def test_overwrite_replaces_member(self, tmp_path):
        from dunders.fm.providers.sevenzip_provider import SevenZipProvider

        work = tmp_path / "w"
        work.mkdir()
        (work / "a.txt").write_text("original")
        archive = tmp_path / "a.7z"
        import subprocess
        subprocess.run([find_7z(), "a", str(archive), "a.txt"], cwd=work,
                       capture_output=True, check=True)
        loc = VfsPath(scheme="7z", root=str(archive), parts=("a.txt",))
        p = SevenZipProvider()
        with p.open_write(loc, overwrite=True) as w:
            w.write(b"EDITED")
        with p.open_read(loc) as fh:
            assert fh.read() == b"EDITED"


def _enter_zip_member(app, archive_name, member):
    desktop = app.query_one(Desktop)
    left = desktop.query_one("#panel-left", Window).content
    assert isinstance(left, FilePanel)
    left.cursor = next(i for i, e in enumerate(left.entries) if e.name == archive_name)
    left.activate()
    left.cursor = next(i for i, e in enumerate(left.entries) if e.name == member)
    return left


def _editor(app):
    desktop = app.query_one(Desktop)
    eds = [w.content for w in desktop.windows if isinstance(w.content, EditorContent)]
    return eds[0] if eds else None


@pytest.mark.asyncio
async def test_f4_edits_zip_member_and_saves_back(tmp_path):
    _make_zip(tmp_path / "a.zip")
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        _enter_zip_member(app, "a.zip", "a.txt")
        app.action_edit()
        await pilot.pause()
        ed = _editor(app)
        assert ed is not None  # an editable editor opened (not a read-only viewer)
        # Replace the buffer content and save.
        ed._editor.buffer.lines = ["changed in archive"]
        ed._save()
        await pilot.pause()
        with zipfile.ZipFile(tmp_path / "a.zip") as zf:
            assert zf.read("a.txt").decode() == "changed in archive"
            assert zf.read("dir/b.txt") == b"keep me"


@pytest.mark.asyncio
async def test_f8_deletes_zip_member(tmp_path):
    from dunders.fm.dialogs import ConfirmDialog

    _make_zip(tmp_path / "a.zip")  # a.txt + dir/b.txt
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        _enter_zip_member(app, "a.zip", "a.txt")
        app.action_delete()
        await pilot.pause()
        app.query_one(ConfirmDialog).action_confirm()
        for _ in range(20):
            await pilot.pause()
        with zipfile.ZipFile(tmp_path / "a.zip") as zf:
            names = set(zf.namelist())
        assert "a.txt" not in names
        assert "dir/b.txt" in names  # untouched


@pytest.mark.asyncio
async def test_f4_read_only_provider_member_warns(tmp_path, monkeypatch):
    # A provider without "write" capability -> F4 declines (no editor).
    _make_zip(tmp_path / "a.zip")
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        _enter_zip_member(app, "a.zip", "a.txt")
        # Force the zip provider to look read-only.
        prov = app._vfs_registry.for_scheme("zip")
        monkeypatch.setattr(prov, "capabilities", frozenset({"read"}))
        app.action_edit()
        await pilot.pause()
        assert _editor(app) is None
