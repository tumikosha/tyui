# `we` Console Editor Entry Point — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `we <file>...` console command that opens one editor window per file, stacked as a Turbo-Vision cascade over hidden FM panels.

**Architecture:** New `launch_mode="we"` carrying a list of paths. `TyuiApp` mounts hidden panels (as the existing `editor` mode does) plus N cascaded editor windows of equal, shrunk size — the first file on top/focused at offset (0,0), the last file's bottom-right corner pinned to the desktop corner. Editor-window construction is factored into a shared `_make_editor_window` helper reused by the existing `_open_editor_window`.

**Tech Stack:** Python ≥3.12, Textual, pytest (`asyncio_mode=auto`), `uv`.

**Spec:** `docs/superpowers/specs/2026-05-30-we-console-editor-design.md`

---

## File Structure

- `tyui/app.py` (modify) — `LaunchMode` literal, `__init__` gains `initial_paths`, new `_make_editor_window` helper, `_mount_cascaded_editors`, `"we"` branch in `_mount_initial_windows`, cascade constants. `_open_editor_window` refactored onto the helper.
- `tyui/main.py` (modify) — `main_we()` entry function + `_resolve_we_paths()` testable helper.
- `pyproject.toml` (modify) — add `we = "tyui.main:main_we"` script.
- `tests/fm/test_we_mode.py` (create) — async smoke tests for the `we` mode.
- `tests/fm/test_main_we.py` (create) — unit tests for argv resolution / entry wiring.

---

## Task 1: `we` launch mode + `initial_paths` on the app

**Files:**
- Modify: `tyui/app.py:170` (`LaunchMode`), `tyui/app.py:233-247` (`__init__`)
- Test: `tests/fm/test_we_mode.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fm/test_we_mode.py`:

```python
from pathlib import Path

import pytest

from tyui.app import TyuiApp


def test_we_mode_constructor_stores_paths(tmp_path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("print('a')\n")
    b.write_text("print('b')\n")
    app = TyuiApp(launch_mode="we", initial_paths=[str(a), b])
    assert app.launch_mode == "we"
    assert app.initial_paths == [Path(a), Path(b)]
    # Single-path field stays None in we-mode; no accidental crossover.
    assert app.initial_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_we_mode.py::test_we_mode_constructor_stores_paths -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'initial_paths'`.

- [ ] **Step 3: Add `"we"` to the LaunchMode literal**

In `tyui/app.py:170`, change:

```python
LaunchMode = Literal["fm", "editor", "cli"]
```
to:
```python
LaunchMode = Literal["fm", "editor", "cli", "we"]
```

- [ ] **Step 4: Add the `initial_paths` parameter**

In `tyui/app.py`, update the `__init__` signature (around line 233-238):

```python
    def __init__(
        self,
        *,
        launch_mode: LaunchMode = "fm",
        initial_path: str | Path | None = None,
        initial_paths: list[str | Path] | None = None,
    ) -> None:
```

Then, right after the existing `self.initial_path = ...` assignment (around line 245-247), add:

```python
        self.initial_paths: list[Path] = [
            Path(p).expanduser() for p in (initial_paths or [])
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/fm/test_we_mode.py::test_we_mode_constructor_stores_paths -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tyui/app.py tests/fm/test_we_mode.py
git commit -m "feat(we): add we launch_mode and initial_paths to TyuiApp"
```

---

## Task 2: Extract `_make_editor_window` helper

**Files:**
- Modify: `tyui/app.py:1458-1502` (`_open_editor_window`)
- Test: `tests/fm/test_we_mode.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/fm/test_we_mode.py`:

```python
from tyui.windowing import Window
from tyui.windowing.editor import EditorContent


@pytest.mark.asyncio
async def test_make_editor_window_loads_file(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\n")
    app = TyuiApp(launch_mode="we", initial_paths=[str(f)])
    async with app.run_test() as pilot:
        await pilot.pause()
        win = app._make_editor_window(
            f, position=(3, 2), size=(40, 10), win_id="editor-test"
        )
        assert isinstance(win, Window)
        assert win.id == "editor-test"
        assert isinstance(win.content, EditorContent)
        assert win.content._editor.buffer.file_path == str(f)


@pytest.mark.asyncio
async def test_make_editor_window_none_path_is_untitled(tmp_path):
    app = TyuiApp(launch_mode="we", initial_paths=[])
    async with app.run_test() as pilot:
        await pilot.pause()
        win = app._make_editor_window(
            None, position=(0, 0), size=(40, 10), win_id="editor-untitled"
        )
        assert isinstance(win.content, EditorContent)
        assert win.content._editor.buffer.file_path is None
```

> Verified API: `EditorContent` holds the buffer at `content._editor.buffer`
> (an instance of `tyui.windowing.core.buffer.TextBuffer`) with `.file_path`
> and `.lines: list[str]`. An empty buffer is `lines == [""]`. There is no
> `.text` accessor — use `.lines`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_we_mode.py -k make_editor_window -v`
Expected: FAIL — `AttributeError: 'TyuiApp' object has no attribute '_make_editor_window'`.

- [ ] **Step 3: Add the helper and refactor `_open_editor_window`**

Add this method to `TyuiApp` (place it directly above `_open_editor_window` near line 1458):

```python
    def _make_editor_window(
        self,
        path: Path | None,
        *,
        position: tuple[int, int],
        size: tuple[int, int],
        win_id: str,
    ) -> Window:
        """Build a focusable editor Window for `path` (None → untitled).

        Single source of truth for editor-window construction, shared by
        `_open_editor_window` and the `we`-mode cascade. Does NOT add the
        window to the desktop.
        """
        if path is None:
            text = ""
            title = "untitled"
            file_path = None
        else:
            try:
                text = path.read_text()
            except OSError:
                text = ""
            title = path.name
            file_path = str(path)
        content = _FocusableEditorContent(initial_text=text, file_path=file_path)
        return make_window(
            content,
            title=title,
            position=position,
            size=size,
            decorations=Decorations(
                close_box=True, zoom_box=True, minimize_box=True, resize_grip=True
            ),
            id=win_id,
        )
```

Then, in `_open_editor_window`, replace the editable-editor branch (the `else`
that currently builds `content = _FocusableEditorContent(...)`, `title`,
`win_id`) plus the `make_window(...)` call so the editor case routes through the
helper. Concretely, the existing block at lines ~1485-1497:

```python
            else:
                content = _FocusableEditorContent(initial_text=text, file_path=str(path))
                title = path.name
                win_id = f"editor-{seq}"
        dw, dh = self.desktop.usable_size.width, self.desktop.usable_size.height
        win = make_window(
            content,
            title=title,
            position=(0, 0),
            size=(dw, dh),
            decorations=Decorations(close_box=True, zoom_box=True, minimize_box=True, resize_grip=True),
            id=win_id,
        )
```

becomes:

```python
            else:
                dw = self.desktop.usable_size.width
                dh = self.desktop.usable_size.height
                win = self._make_editor_window(
                    path,
                    position=(0, 0),
                    size=(dw, dh),
                    win_id=f"editor-{seq}",
                )
                win._saved_rect = (
                    Offset(2, 1), Size(max(1, dw - 4), max(1, dh - 2))
                )
                win.maximized = True
                self.desktop.add_window(win)
                if self._pre_menu_focus is not None or self._pre_menu_window is not None:
                    self._pre_menu_window = win
                    self._pre_menu_focus = None
                return
        # --- viewer / hex branch (read_only) keeps the original flow ---
        dw, dh = self.desktop.usable_size.width, self.desktop.usable_size.height
        win = make_window(
            content,
            title=title,
            position=(0, 0),
            size=(dw, dh),
            decorations=Decorations(close_box=True, zoom_box=True, minimize_box=True, resize_grip=True),
            id=win_id,
        )
```

> The viewer/hex branches still set `content`, `title`, `win_id` above, so the
> trailing `make_window(...)` (kept intact for them) plus the existing
> `_saved_rect`/`maximized`/`add_window`/`_pre_menu_*` lines below continue to
> serve the read-only case unchanged. Only the editable branch now early-returns
> through the helper.

- [ ] **Step 4: Run the new + existing editor tests**

Run:
```bash
pytest tests/fm/test_we_mode.py -k make_editor_window -v
pytest tests/fm/test_app_skeleton.py -v
```
Expected: PASS for the helper tests AND all pre-existing app-skeleton tests
(the refactor must not regress F4/Enter editor opening).

- [ ] **Step 5: Commit**

```bash
git add tyui/app.py tests/fm/test_we_mode.py
git commit -m "refactor(app): extract _make_editor_window shared helper"
```

---

## Task 3: Cascade mounting in `we` mode

**Files:**
- Modify: `tyui/app.py` — add constants near other module constants (e.g. just below `LaunchMode` at line 170); add `_mount_cascaded_editors`; add `"we"` branch in `_mount_initial_windows` (after the `editor` branch, ~line 856)
- Test: `tests/fm/test_we_mode.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/fm/test_we_mode.py`:

```python
from tyui.windowing import Desktop


def _editor_windows(app):
    desktop = app.query_one(Desktop)
    return [w for w in desktop.windows if w.id and w.id.startswith("editor-")]


@pytest.mark.asyncio
async def test_we_three_files_cascade(tmp_path):
    files = []
    for name in ("a.py", "b.py", "c.py"):
        p = tmp_path / name
        p.write_text(f"# {name}\n")
        files.append(p)
    app = TyuiApp(launch_mode="we", initial_paths=[str(p) for p in files])
    async with app.run_test() as pilot:
        await pilot.pause()
        desktop = app.query_one(Desktop)
        # 3 editor windows mounted.
        eds = _editor_windows(app)
        assert len(eds) == 3
        # Panels exist but are hidden (not in the visible windows list).
        visible_ids = {w.id for w in desktop.windows}
        assert {"panel-left", "panel-right"}.isdisjoint(visible_ids)
        # First file is focused and on top (last in z-order list).
        top = desktop.windows[-1]
        assert top is desktop.focused_window
        assert top.content._editor.buffer.file_path == str(files[0])
        # Offsets per file index: (0,0), (2,1), (4,2).
        by_path = {w.content._editor.buffer.file_path: w for w in eds}
        assert tuple(by_path[str(files[0])].styles.offset) == (0, 0)
        assert tuple(by_path[str(files[1])].styles.offset) == (2, 1)
        assert tuple(by_path[str(files[2])].styles.offset) == (4, 2)
        # All windows share one size; last file's bottom-right pins to the corner.
        W = desktop.usable_size.width
        H = desktop.usable_size.height
        last = by_path[str(files[2])]
        assert last.styles.offset.x + last.size.width == W
        assert last.styles.offset.y + last.size.height == H


@pytest.mark.asyncio
async def test_we_missing_file_opens_empty_buffer(tmp_path):
    missing = tmp_path / "nope.py"
    app = TyuiApp(launch_mode="we", initial_paths=[str(missing)])
    async with app.run_test() as pilot:
        await pilot.pause()
        eds = _editor_windows(app)
        assert len(eds) == 1
        assert eds[0].content._editor.buffer.file_path == str(missing)
        assert eds[0].content._editor.buffer.lines == [""]


@pytest.mark.asyncio
async def test_we_no_args_opens_one_untitled(tmp_path):
    app = TyuiApp(launch_mode="we", initial_paths=[])
    async with app.run_test() as pilot:
        await pilot.pause()
        eds = _editor_windows(app)
        assert len(eds) == 1
        assert eds[0].content._editor.buffer.file_path is None


@pytest.mark.asyncio
async def test_we_directory_arg_is_skipped(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    f = tmp_path / "real.py"
    f.write_text("x = 1\n")
    app = TyuiApp(launch_mode="we", initial_paths=[str(d), str(f)])
    async with app.run_test() as pilot:
        await pilot.pause()
        eds = _editor_windows(app)
        # Directory dropped → only the real file opens.
        assert len(eds) == 1
        assert eds[0].content._editor.buffer.file_path == str(f)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fm/test_we_mode.py -k "we_three or we_missing or we_no_args or we_directory" -v`
Expected: FAIL — the `we` branch is unhandled, so `_mount_initial_windows`
raises `ValueError: unknown launch_mode: 'we'`.

- [ ] **Step 3: Add cascade constants**

In `tyui/app.py`, directly below the `LaunchMode` definition (line ~170), add:

```python
# `we`-mode cascade geometry: each successive editor window is shifted by
# (_WE_CASCADE_DX, _WE_CASCADE_DY); all windows share one shrunk size so the
# last file's bottom-right corner pins to the desktop corner.
_WE_CASCADE_DX = 2
_WE_CASCADE_DY = 1
_WE_MIN_W = 20
_WE_MIN_H = 6
```

- [ ] **Step 4: Add the `we` branch to `_mount_initial_windows`**

In `tyui/app.py`, after the `if self.launch_mode == "editor":` block ends
(`return` near line 856) and before the `cli` block, insert:

```python
        if self.launch_mode == "we":
            self._add_panel_windows(cwd, visible=False)
            self._mount_cascaded_editors()
            return
```

- [ ] **Step 5: Implement `_mount_cascaded_editors`**

Add this method to `TyuiApp` (place it right after `_mount_initial_windows`):

```python
    def _mount_cascaded_editors(self) -> None:
        assert self.desktop is not None
        # Filter: directories are skipped; missing files are kept (they open
        # as an empty buffer that saves to that path on Ctrl+S).
        files: list[Path] = []
        for p in self.initial_paths:
            if p.is_dir():
                self.notify(f"skipped {p}: not a file", severity="warning")
                continue
            files.append(p)

        W = self.desktop.usable_size.width
        H = self.desktop.usable_size.height

        if not files:
            # No usable paths → a single untitled editor window.
            self._editor_seq += 1
            win = self._make_editor_window(
                None, position=(0, 0), size=(max(_WE_MIN_W, W), max(_WE_MIN_H, H)),
                win_id=f"editor-{self._editor_seq}",
            )
            self.desktop.add_window(win)
            return

        n = len(files)
        cw = max(_WE_MIN_W, W - (n - 1) * _WE_CASCADE_DX)
        ch = max(_WE_MIN_H, H - (n - 1) * _WE_CASCADE_DY)

        # Add in reverse so the first file is added LAST → ends up on top of the
        # z-order and focused, sitting at offset (0, 0).
        for i in reversed(range(n)):
            self._editor_seq += 1
            win = self._make_editor_window(
                files[i],
                position=(i * _WE_CASCADE_DX, i * _WE_CASCADE_DY),
                size=(cw, ch),
                win_id=f"editor-{self._editor_seq}",
            )
            self.desktop.add_window(win)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/fm/test_we_mode.py -v`
Expected: PASS (all cascade + edge-case tests).

- [ ] **Step 7: Run the full fm suite for regressions**

Run: `pytest tests/fm/ -q`
Expected: PASS (no regression in fm/editor/cli modes).

- [ ] **Step 8: Commit**

```bash
git add tyui/app.py tests/fm/test_we_mode.py
git commit -m "feat(we): mount cascaded editor windows in we mode"
```

---

## Task 4: `main_we` entry point + `pyproject` script

**Files:**
- Modify: `tyui/main.py` — add `_resolve_we_paths` + `main_we`
- Modify: `pyproject.toml:[project.scripts]`
- Test: `tests/fm/test_main_we.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fm/test_main_we.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_main_we.py -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_we_paths' from 'tyui.main'`.

- [ ] **Step 3: Implement `_resolve_we_paths` and `main_we`**

In `tyui/main.py`, add at the end (after `main`, before the
`if __name__ == "__main__":` guard):

```python
def _resolve_we_paths(argv: list[str]) -> list[str]:
    """Return the list of positional file paths for the `we` command."""
    parser = argparse.ArgumentParser(
        prog="we",
        description="we — open one editor window per file, cascaded.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Files to edit. Each opens in its own cascaded editor window. "
             "Missing files open empty; directories are skipped.",
    )
    return parser.parse_args(argv).paths


def main_we() -> None:
    paths = _resolve_we_paths(sys.argv[1:])
    TyuiApp(launch_mode="we", initial_paths=paths).run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/fm/test_main_we.py -v`
Expected: PASS

- [ ] **Step 5: Register the `we` console script**

In `pyproject.toml`, under `[project.scripts]`:

```toml
[project.scripts]
tyui = "tyui.main:main"
we = "tyui.main:main_we"
```

- [ ] **Step 6: Verify the entry resolves**

Run: `python -c "from tyui.main import main_we; print(main_we.__name__)"`
Expected: prints `main_we` with no import error.

- [ ] **Step 7: Commit**

```bash
git add tyui/main.py tests/fm/test_main_we.py pyproject.toml
git commit -m "feat(we): add we console entry point and script"
```

---

## Task 5: Full verification

- [ ] **Step 1: Run the complete suite**

Run: `pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 2: Lint**

Run: `ruff check`
Expected: no new findings in `tyui/app.py`, `tyui/main.py`, `tests/fm/test_we_mode.py`, `tests/fm/test_main_we.py`.

- [ ] **Step 3: Manual smoke (optional, requires a TTY)**

Run: `python -m tyui.main` is the fm path; for `we`, after `pip install -e .`:
`we tyui/app.py tyui/main.py` → first file on top/focused, second peeks
bottom-right. Esc closes the top editor.

- [ ] **Step 4: Final commit if any lint fixups were needed**

```bash
git add -A
git commit -m "chore(we): lint and verification fixups"
```

---

## Self-Review notes

- **Spec coverage:** entry point (Task 4), hidden panels + cascade (Task 3),
  geometry incl. shrunk size & pinned corner (Task 3 test asserts it), helper
  refactor (Task 2), launch mode/paths (Task 1), all five edge cases (Task 3
  + Task 1). All spec sections map to a task.
- **Directory-skip notification:** spec said "statusbar"; implementation uses
  Textual's `self.notify(...)` toast (the standard transient channel). Tests
  assert the skip by window count, not the toast text, so the mechanism is free
  to be either.
- **Buffer accessor (verified):** the buffer lives at
  `win.content._editor.buffer` (`TextBuffer`) with `.file_path` and
  `.lines: list[str]`; empty buffer is `lines == [""]`. All tests use this path.
- **Type consistency:** `_make_editor_window(path, *, position, size, win_id)`
  signature is identical across Task 2 (definition + `_open_editor_window` call)
  and Task 3 (cascade calls). Constants `_WE_CASCADE_DX/DY`, `_WE_MIN_W/H`
  defined once in Task 3 Step 3.
```
