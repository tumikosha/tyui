"""Both panels must share the app's single VfsRegistry, so a provider
registered once (e.g. by a plugin) is visible to every panel.
"""

import pytest

from dunders.app import DundersApp
from dunders.fm.file_panel import FilePanel
from dunders.windowing import Desktop, Window


def _panels(app: DundersApp):
    desktop = app.query_one(Desktop)
    left = desktop.query_one("#panel-left", Window).content
    right = desktop.query_one("#panel-right", Window).content
    assert isinstance(left, FilePanel) and isinstance(right, FilePanel)
    return left, right


@pytest.mark.asyncio
async def test_panels_share_app_registry(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        left, right = _panels(app)
        assert left._registry is app._vfs_registry
        assert right._registry is app._vfs_registry


@pytest.mark.asyncio
async def test_provider_registered_on_app_is_visible_to_panels(tmp_path):
    app = DundersApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        left, _ = _panels(app)

        class _Dummy:
            scheme = "dummy"
            capabilities = frozenset({"read"})

        app._vfs_registry.register(_Dummy())
        # The panel resolves the freshly-registered scheme through the shared
        # registry without being recreated.
        assert "dummy" in left._registry.schemes()
