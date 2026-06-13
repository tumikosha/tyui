"""The "_" dunders menu: providers declare a display name + prefix, are listed,
and selecting one opens it in the active panel via resolve_target.
"""

import zipfile

import pytest

from dunders.app import DundersApp
from dunders.core.vfs import VfsPath
from dunders.fm.file_panel import FilePanel
from dunders.fm.providers.sevenzip_provider import SevenZipProvider, find_7z

_needs_7z = pytest.mark.skipif(find_7z() is None, reason="no 7z binary on PATH")


def _active(app: DundersApp) -> FilePanel:
    panel = app._active_panel()
    assert isinstance(panel, FilePanel)
    return panel


class TestSevenZipResolveTarget:
    def test_existing_file_returns_locator(self, tmp_path):
        # An existing archive is opened as-is (no recreate; no binary needed).
        archive = tmp_path / "x.7z"
        archive.write_bytes(b"not really 7z but exists")
        loc = SevenZipProvider().resolve_target("x.7z", base=VfsPath.local(tmp_path))
        assert loc == VfsPath(scheme="7z", root=str(archive), parts=())

    def test_non_file_base_rejected(self):
        base = VfsPath(scheme="7z", root="/a.7z", parts=())
        assert SevenZipProvider().resolve_target("x.7z", base=base) is None

    @_needs_7z
    def test_missing_file_is_created(self, tmp_path):
        loc = SevenZipProvider().resolve_target("fresh.7z", base=VfsPath.local(tmp_path))
        assert loc is not None
        assert (tmp_path / "fresh.7z").is_file()


@pytest.mark.asyncio
async def test_dunders_menu_lists_zip(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        # zip declares display_name + resolve_target -> it is openable.
        openable = dict(app._openable_dunders())
        assert openable.get("zip") == "Zip archiver"
        # The "_" brand menu exists and carries an entry for it.
        brand = next(m for m in app.menu_bar.menus if m.label == "_")
        labels = [getattr(it, "label", None) for it in brand.items]
        assert "Zip archiver" in labels
        # Its command is registered.
        assert app.command_registry.get("dunder.open.zip") is not None


@pytest.mark.asyncio
async def test_open_dunder_creates_and_enters_archive(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        panel = _active(app)
        # Simulate selecting "Zip archiver" and typing a name.
        app._do_open_dunder("zip", "fresh.zip")
        await pilot.pause()
        out = tmp_path / "fresh.zip"
        assert out.exists()  # created empty, browsable
        assert panel.cwd_loc == VfsPath(scheme="zip", root=str(out), parts=())
        # An empty new archive lists only the parent row.
        assert [e.name for e in panel.entries] == [".."]


@pytest.mark.asyncio
async def test_open_dunder_opens_existing_archive(tmp_path):
    archive = tmp_path / "have.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("member.txt", b"hi")
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        panel = _active(app)
        app._do_open_dunder("zip", "have.zip")
        await pilot.pause()
        assert panel.cwd_loc.scheme == "zip"
        assert "member.txt" in {e.name for e in panel.entries}


@pytest.mark.asyncio
async def test_open_dunder_unresolvable_warns_no_navigation(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        panel = _active(app)

        class _NeverResolves:
            scheme = "nope"
            display_name = "Nope"
            capabilities = frozenset({"read"})
            def resolve_target(self, spec, *, base):
                return None  # always declines

        app._vfs_registry.register(_NeverResolves())
        before = panel.cwd_loc
        app._do_open_dunder("nope", "whatever")  # resolver returns None
        await pilot.pause()
        assert panel.cwd_loc == before  # no navigation
