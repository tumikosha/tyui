"""App-level: a plugin in the local dir loads at startup and its provider is
live in the panels; op.* events reach subscribers.
"""

from textwrap import dedent

import pytest

from dunders.config.user_config import config_dir
from dunders.app import DundersApp
from dunders.fm.actions import OpResult
from dunders.fm.file_panel import FilePanel
from dunders.windowing import Desktop, Window

_PLUGIN_SRC = dedent('''
    class _DemoProvider:
        scheme = "demo"
        capabilities = frozenset({"read"})

    class _DemoPlugin:
        name = "demo-plugin"
        version = "0.1.0"
        def register(self, api):
            api.vfs.register(_DemoProvider())

    plugin = _DemoPlugin()
''')


def _install_plugin() -> None:
    # config_dir() honours the autouse XDG_CONFIG_HOME tmp fixture.
    pdir = config_dir() / "dunders"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "demo.py").write_text(_PLUGIN_SRC)


@pytest.mark.asyncio
async def test_plugin_loads_at_startup_and_provider_reaches_panels(tmp_path):
    _install_plugin()
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    assert "demo-plugin" in app.loaded_plugins  # registered in __init__
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        left = app.query_one(Desktop).query_one("#panel-left", Window).content
        assert isinstance(left, FilePanel)
        assert "demo" in left._registry.schemes()  # shared registry sees it


@pytest.mark.asyncio
async def test_no_plugins_env_skips_discovery(tmp_path, monkeypatch):
    _install_plugin()
    monkeypatch.setenv("DUNDERS_NO_PLUGINS", "1")
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    assert app.loaded_plugins == []


@pytest.mark.asyncio
async def test_op_event_emitted_to_subscribers(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = []
        app.events.on("op.copy.done", lambda r: seen.append(r))
        # _finish_op runs on the UI thread after a worker op; call it directly.
        from dunders.fm.dialogs import ProgressDialog
        prog = ProgressDialog(title="Copying", total=1)
        app._finish_op("copy", prog, OpResult(succeeded=[tmp_path]))
        await pilot.pause()
        assert len(seen) == 1
        assert isinstance(seen[0], OpResult)
