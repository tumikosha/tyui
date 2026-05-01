from __future__ import annotations

import pytest

from tyui.app import TyuiApp


@pytest.mark.asyncio
async def test_cd_command_changes_active_panel_cwd(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    app = TyuiApp(launch_mode="fm", initial_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_command_submitted_for_test(f"cd {sub}", anonymous=False)
        await pilot.pause()
        assert app._panel_cwd_for_test().resolve() == sub.resolve()


@pytest.mark.asyncio
async def test_named_target_creates_console_window(tmp_path):
    app = TyuiApp(launch_mode="fm", initial_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app._on_command_submitted_for_test("@build echo hi", anonymous=False)
        for _ in range(50):
            await pilot.pause()
            target = app.console_registry.get("console-build")
            if target is not None and not target.busy:
                break
        assert app.console_registry.get("console-build") is not None


@pytest.mark.asyncio
async def test_ctrl_o_creates_default_console(tmp_path):
    app = TyuiApp(launch_mode="fm", initial_path=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_toggle_console()
        await pilot.pause()
        assert app.console_registry.get("console-default") is not None
