"""we-mode hotkeys: command-line focus + cascade/tile arrangement.

These cover the terminal-independent rebind of the command-line focus
(alt+c stays, but ctrl+e reaches the app even on macOS where Option+C is
swallowed as "ç") and the new Cascade/Tile hotkeys, which previously were
only reachable via the menu / command palette.
"""
import tempfile
from pathlib import Path

import pytest

from tyui.app import TyuiApp
from tyui.fm.commandline import CommandLine


def _make_file(text: str = "print(1)\n") -> str:
    d = tempfile.mkdtemp()
    f = Path(d) / "a.py"
    f.write_text(text)
    return str(f)


@pytest.mark.asyncio
async def test_we_ctrl_e_focuses_command_line():
    app = TyuiApp(launch_mode="we", initial_paths=[_make_file()])
    async with app.run_test() as pilot:
        await pilot.pause()
        # Focus starts on the editor, not the command line.
        cmd_input = app.query_one(CommandLine)._input
        assert app.focused is not cmd_input
        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app.focused is cmd_input


@pytest.mark.asyncio
async def test_we_cascade_hotkey_dispatches():
    app = TyuiApp(launch_mode="we", initial_paths=[_make_file()])
    async with app.run_test() as pilot:
        await pilot.pause()
        calls: list[str] = []
        orig = app.manager.cascade
        app.manager.cascade = lambda: (calls.append("cascade"), orig())[1]
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert calls == ["cascade"]


@pytest.mark.asyncio
async def test_we_tile_vertical_hotkey_dispatches():
    app = TyuiApp(launch_mode="we", initial_paths=[_make_file()])
    async with app.run_test() as pilot:
        await pilot.pause()
        calls: list[str] = []
        orig = app.manager.tile_vertical
        app.manager.tile_vertical = lambda: (calls.append("tile_v"), orig())[1]
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert calls == ["tile_v"]
