from tyui.main import _resolve_we_paths, main_we


def test_resolve_we_paths_multiple():
    assert _resolve_we_paths(["a.py", "b.py", "c.py"]) == ["a.py", "b.py", "c.py"]


def test_resolve_we_paths_empty():
    assert _resolve_we_paths([]) == []


def test_main_we_constructs_we_app(monkeypatch):
    captured = {}

    class _FakeApp:
        def __init__(self, *, launch_mode, initial_paths):
            captured["launch_mode"] = launch_mode
            captured["initial_paths"] = initial_paths

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr("tyui.main.TyuiApp", _FakeApp)
    monkeypatch.setattr("sys.argv", ["we", "a.py", "b.py"])
    main_we()

    assert captured["launch_mode"] == "we"
    assert captured["initial_paths"] == ["a.py", "b.py"]
    assert captured["ran"] is True
