from tyui.main import _resolve_we_launch, _resolve_we_paths, main_we


def test_resolve_we_paths_multiple():
    assert _resolve_we_paths(["a.py", "b.py", "c.py"]) == ["a.py", "b.py", "c.py"]


def test_resolve_we_paths_empty():
    assert _resolve_we_paths([]) == []


def test_resolve_we_launch_no_paths_falls_back_to_fm():
    # No file argument -> file manager (both panels), not an empty editor.
    assert _resolve_we_launch([]) == ("fm", None, [])


def test_resolve_we_launch_directory_opens_panels(tmp_path):
    assert _resolve_we_launch([str(tmp_path)]) == ("fm", str(tmp_path), [])


def test_resolve_we_launch_files_use_we_mode():
    assert _resolve_we_launch(["a.py", "b.py"]) == ("we", None, ["a.py", "b.py"])


def _capture_app(monkeypatch):
    captured = {}

    class _FakeApp:
        def __init__(self, *, launch_mode, initial_path=None, initial_paths=None):
            captured["launch_mode"] = launch_mode
            captured["initial_path"] = initial_path
            captured["initial_paths"] = initial_paths

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr("tyui.main.TyuiApp", _FakeApp)
    return captured


def test_main_we_constructs_we_app(monkeypatch):
    captured = _capture_app(monkeypatch)
    monkeypatch.setattr("sys.argv", ["we", "a.py", "b.py"])
    main_we()

    assert captured["launch_mode"] == "we"
    assert captured["initial_paths"] == ["a.py", "b.py"]
    assert captured["ran"] is True


def test_main_we_without_args_opens_file_manager(monkeypatch):
    captured = _capture_app(monkeypatch)
    monkeypatch.setattr("sys.argv", ["we"])
    main_we()

    assert captured["launch_mode"] == "fm"
    assert captured["initial_path"] is None
    assert captured["ran"] is True


def test_main_we_with_directory_seeds_panels(monkeypatch, tmp_path):
    captured = _capture_app(monkeypatch)
    monkeypatch.setattr("sys.argv", ["we", str(tmp_path)])
    main_we()

    assert captured["launch_mode"] == "fm"
    assert captured["initial_path"] == str(tmp_path)
    assert captured["ran"] is True
