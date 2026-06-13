"""ZipProvider append-write + file->zip via the generic transfer engine."""

import zipfile
from pathlib import Path

import pytest

from dunders.core.vfs import VfsPath
from dunders.fm.providers.zip_provider import ZipProvider
from dunders.fm.vfs_engine import transfer
from dunders.fm.vfs_local import default_registry


def _make_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("existing.txt", b"old")
    return path


def _root(archive: Path) -> VfsPath:
    return VfsPath(scheme="zip", root=str(archive), parts=())


def _names(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as zf:
        return set(zf.namelist())


class TestProviderWrite:
    def test_capability(self):
        assert "write" in ZipProvider().capabilities

    def test_open_write_appends_member(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        loc = VfsPath(scheme="zip", root=str(archive), parts=("new.txt",))
        with ZipProvider().open_write(loc) as w:
            w.write(b"hello")
        assert _names(archive) == {"existing.txt", "new.txt"}
        with zipfile.ZipFile(archive) as zf:
            assert zf.read("new.txt") == b"hello"

    def test_open_write_refuses_existing_member(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        loc = VfsPath(scheme="zip", root=str(archive), parts=("existing.txt",))
        with pytest.raises(FileExistsError):
            ZipProvider().open_write(loc)
        # archive untouched
        with zipfile.ZipFile(archive) as zf:
            assert zf.read("existing.txt") == b"old"

    def test_mkdir_adds_dir_entry(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        ZipProvider().mkdir(_root(archive), "sub")
        assert "sub/" in _names(archive)

    def test_delete_unsupported(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        loc = VfsPath(scheme="zip", root=str(archive), parts=("existing.txt",))
        with pytest.raises(OSError):
            ZipProvider().delete([loc])


class TestFileIntoZip:
    def _reg(self):
        return default_registry()

    def test_copy_local_file_into_zip(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        src = tmp_path / "src.txt"
        src.write_text("payload")
        res = transfer(
            self._reg(), [VfsPath.local(src)], _root(archive), mode="copy"
        )
        assert not res.errors
        assert "src.txt" in _names(archive)
        with zipfile.ZipFile(archive) as zf:
            assert zf.read("src.txt") == b"payload"

    def test_copy_local_dir_into_zip_recursively(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        d = tmp_path / "dir"
        (d / "sub").mkdir(parents=True)
        (d / "top.txt").write_text("t")
        (d / "sub" / "deep.txt").write_text("dd")
        res = transfer(
            self._reg(), [VfsPath.local(d)], _root(archive), mode="copy"
        )
        assert not res.errors
        names = _names(archive)
        assert "dir/top.txt" in names
        assert "dir/sub/deep.txt" in names

    def test_copy_into_subdir_of_archive(self, tmp_path):
        # Append at a sub-path locator (panel browsed into dir/ inside the zip).
        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("dir/keep.txt", b"k")
        src = tmp_path / "added.txt"
        src.write_text("added")
        dest = VfsPath(scheme="zip", root=str(archive), parts=("dir",))
        res = transfer(self._reg(), [VfsPath.local(src)], dest, mode="copy")
        assert not res.errors
        assert "dir/added.txt" in _names(archive)

    def test_conflict_is_reported_not_crash(self, tmp_path):
        archive = _make_zip(tmp_path / "a.zip")
        src = tmp_path / "existing.txt"  # same name as a member already inside
        src.write_text("new content")
        res = transfer(
            self._reg(), [VfsPath.local(src)], _root(archive), mode="copy"
        )
        assert len(res.errors) == 1
        assert "exist" in res.errors[0].reason.lower()
        # original member untouched
        with zipfile.ZipFile(archive) as zf:
            assert zf.read("existing.txt") == b"old"
