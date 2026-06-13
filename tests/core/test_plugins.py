"""Plugin runtime: EventBus, discovery/registration, and the SDK facade."""

from textwrap import dedent

from dunders.core.plugins import EventBus, PluginApi, discover_plugins, load_plugins
from dunders.core.vfs import VfsRegistry


class TestEventBus:
    def test_emit_calls_subscribers(self):
        bus = EventBus()
        seen = []
        bus.on("op.copy.done", lambda p: seen.append(p))
        bus.emit("op.copy.done", "payload")
        assert seen == ["payload"]

    def test_unknown_event_is_noop(self):
        EventBus().emit("nothing.here", 1)  # must not raise

    def test_handler_error_is_swallowed(self):
        bus = EventBus()
        bus.on("e", lambda _p: (_ for _ in ()).throw(RuntimeError("boom")))
        ok = []
        bus.on("e", lambda _p: ok.append(True))
        bus.emit("e", None)  # first handler raises, second still runs
        assert ok == [True]


# A plugin file dropped into the local plugin dir.
_PLUGIN_SRC = dedent('''
    from dunders.sdk import DunderPlugin, PluginApi

    class _DemoProvider:
        scheme = "demo"
        capabilities = frozenset({"read"})

    class _DemoPlugin:
        name = "demo-plugin"
        version = "0.1.0"
        def register(self, api):
            api.vfs.register(_DemoProvider())
            api.events.on("op.copy.done", lambda r: None)

    plugin = _DemoPlugin()
''')


def _api():
    return PluginApi(vfs=VfsRegistry(), events=EventBus())


class TestDiscovery:
    def test_discovers_local_py_file(self, tmp_path):
        (tmp_path / "demo.py").write_text(_PLUGIN_SRC)
        plugins = discover_plugins(extra_dir=tmp_path)
        names = {p.name for p in plugins}
        assert "demo-plugin" in names

    def test_load_registers_provider_and_returns_names(self, tmp_path):
        (tmp_path / "demo.py").write_text(_PLUGIN_SRC)
        api = _api()
        loaded = load_plugins(api, extra_dir=tmp_path)
        assert "demo-plugin" in loaded
        assert "demo" in api.vfs.schemes()

    def test_empty_dir_loads_nothing(self, tmp_path):
        assert load_plugins(_api(), extra_dir=tmp_path) == []

    def test_underscore_files_skipped(self, tmp_path):
        (tmp_path / "_private.py").write_text(_PLUGIN_SRC)
        assert discover_plugins(extra_dir=tmp_path) == []

    def test_broken_plugin_is_skipped_not_fatal(self, tmp_path):
        (tmp_path / "bad.py").write_text("import nonexistent_module_xyz\n")
        (tmp_path / "good.py").write_text(_PLUGIN_SRC)
        loaded = load_plugins(_api(), extra_dir=tmp_path)
        assert loaded == ["demo-plugin"]  # bad one skipped, good one loaded

    def test_register_failure_is_swallowed(self, tmp_path):
        src = dedent('''
            class _P:
                name = "explodes"
                version = "0.1"
                def register(self, api):
                    raise RuntimeError("nope")
            plugin = _P()
        ''')
        (tmp_path / "boom.py").write_text(src)
        assert load_plugins(_api(), extra_dir=tmp_path) == []


class TestSdkFacade:
    def test_facade_exposes_stable_surface(self):
        import dunders.sdk as sdk

        for name in (
            "DunderPlugin", "PluginApi", "EventBus",
            "VfsPath", "VfsProvider", "VfsRegistry",
            "FileEntry", "OpResult", "OpError",
            "WindowContent", "WindowCommand",
        ):
            assert hasattr(sdk, name), name
