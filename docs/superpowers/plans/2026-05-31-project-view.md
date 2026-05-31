# Project View (F2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an F2 "Project View" that docks the active file panel as a 1/4-width project tree on its own side with the file's editor filling the remaining 3/4.

**Architecture:** One new geometry helper (`_layout_project_view`) plus one app action (`action_project_view`) that branches on focus context (panel vs editor). State is a single field `_project_tree_panel_id`. F2 is registered as a focus-scoped `WindowCommand` on the file panel and on the app-layer editor subclass; both route to the single action. Exit reuses the existing Ctrl+1 / Ctrl+2 panel toggle, which clears the state field. The existing resize hook re-applies the split.

**Tech Stack:** Python 3.12, Textual, pytest (`asyncio_mode = auto`), the in-repo `tyui.windowing` framework.

**Spec:** `docs/superpowers/specs/2026-05-31-project-view-design.md`

---

## Background facts (verified in code)

- `desktop.usable_size` is a `Size` with `.width` / `.height`. The Desktop's CSS
  margin already excludes MenuBar + CommandLine + StatusBar, so the full usable
  area is what windows should fill (see `_tile_panels`, `tyui/app.py:1053`).
- Panels are queried by id: `desktop.query_one("#panel-left", Window)` /
  `"#panel-right"`. A `FilePanel` is `win.content`.
- `Desktop.hide_window` / `show_window` / `minimize_window` / `restore_window`
  move windows between `desktop.windows`, `desktop.hidden_windows`,
  `desktop.minimized_windows` (`tyui/windowing/desktop.py:274-316`).
- `_make_editor_window(path, *, position, size, win_id, text)` builds a
  `_FocusableEditorContent` window **not maximized** and does **not** add it to
  the desktop (`tyui/app.py:1686`). `_open_editor_window` is the maximized path —
  do not reuse it here.
- `_is_editor_focused()` returns True when `desktop.focused_window.content` is an
  `EditorContent` (`tyui/app.py:813`).
- `_active_panel()` falls back to `panel-left` even when an editor is focused, so
  it must NOT be used to decide panel-vs-editor context. Use `_is_editor_focused()`
  first (`tyui/app.py:1204`).
- The resize hook is `_relayout_after_resize` (`tyui/app.py:537`), wired via
  `self.desktop.on_resized = self._relayout_after_resize` (`tyui/app.py:335`).
- `_toggle_panel` (`tyui/app.py:1154`) is the Ctrl+1 / Ctrl+2 handler — the exit path.
- Geometry in tests is asserted via `win.region.x` / `.region.width` /
  `.region.height` (see `tests/fm/test_resize_relayout.py`).
- `Offset` and `Size` are already imported in `tyui/app.py`.
- File-panel F-keys live in `FilePanel.get_commands()` (`tyui/fm/file_panel.py:794`).
- The editor command list is `EditorContent.get_commands()`
  (`tyui/windowing/editor/content.py:255`). To keep the generic windowing layer
  app-agnostic, the F2 editor command is added in the **app-layer** subclass
  `_FocusableEditorContent.get_commands()` (`tyui/app.py:86`), NOT in `EditorContent`.

## File Structure

- **Modify** `tyui/app.py`:
  - Add field `self._project_tree_panel_id: str | None = None` in `__init__`.
  - Add `_layout_project_view(self, tree_win, editor_win)`.
  - Add `action_project_view(self)` + `_project_view_from_panel(self, panel)` +
    `_project_view_from_editor(self)` + helper `_window_of(self, content)`.
  - Add `get_commands` override on `_FocusableEditorContent`.
  - Edit `_relayout_after_resize` to re-apply Project View when active.
  - Edit `_toggle_panel` to clear `_project_tree_panel_id`.
- **Modify** `tyui/fm/file_panel.py`: add the `panel.project_view` F2 command.
- **Create** `tests/fm/test_project_view.py`.

---

### Task 1: Geometry helper `_layout_project_view` + state field

**Files:**
- Modify: `tyui/app.py` (add field in `__init__`; add method near `_tile_panels`, ~line 1093)
- Test: `tests/fm/test_project_view.py`

- [ ] **Step 1: Write the failing test**

Create `tests/fm/test_project_view.py`:

```python
"""Project View (F2): 1/4 tree on its own side + 3/4 editor filling the rest."""

from __future__ import annotations

import pytest

from tyui.app import TyuiApp
from tyui.windowing import Window
from tyui.windowing.editor import EditorContent


async def _settle(pilot):
    await pilot.pause()
    await pilot.pause()


def _editor_windows(app):
    return [w for w in app.desktop.windows if isinstance(w.content, EditorContent)]


async def test_layout_project_view_left_tree_geometry():
    app = TyuiApp(launch_mode="fm")
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        left = app.desktop.query_one("#panel-left", Window)
        right = app.desktop.query_one("#panel-right", Window)
        # Use the right panel as an editor stand-in purely to exercise the math.
        app._layout_project_view(tree_win=left, editor_win=right)
        await _settle(pilot)

        W, H = app.desktop.usable_size
        tree_w = max(8, W // 4)
        assert left.region.x == 0
        assert left.region.width == tree_w
        assert right.region.x == tree_w
        assert left.region.width + right.region.width == W
        assert left.region.height == H


async def test_layout_project_view_right_tree_geometry():
    app = TyuiApp(launch_mode="fm")
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        left = app.desktop.query_one("#panel-left", Window)
        right = app.desktop.query_one("#panel-right", Window)
        # Right panel is the tree; left panel stands in for the editor.
        app._layout_project_view(tree_win=right, editor_win=left)
        await _settle(pilot)

        W, H = app.desktop.usable_size
        tree_w = max(8, W // 4)
        assert right.region.width == tree_w
        assert right.region.x == W - tree_w
        assert left.region.x == 0
        assert left.region.width == W - tree_w
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_project_view.py -k layout -v`
Expected: FAIL — `AttributeError: 'TyuiApp' object has no attribute '_layout_project_view'`.

- [ ] **Step 3: Add the state field**

In `TyuiApp.__init__`, directly after `self._editor_seq = 0` (`tyui/app.py:300`),
add:

```python
        # Project View (F2): id of the panel currently acting as the 1/4 tree,
        # or None when Project View is not active. Drives resize relayout and
        # the editor-side entry point; cleared by _toggle_panel (the exit path).
        self._project_tree_panel_id: str | None = None
```

- [ ] **Step 4: Implement `_layout_project_view`**

Add right after `_tile_panels` (after `tyui/app.py:1093`):

```python
    def _layout_project_view(self, tree_win: Window, editor_win: Window) -> None:
        """Dock `tree_win` as a 1/4-width tree on its own side, `editor_win` 3/4.

        The tree keeps the side its id implies: ``panel-right`` docks right (with
        the editor on the left), every other id docks left. Both windows fill the
        full usable height.
        """
        assert self.desktop is not None
        W, H = self.desktop.usable_size
        if W <= 0 or H <= 0:
            return
        tree_w = max(8, W // 4)
        editor_w = max(3, W - tree_w)
        if tree_win.id == "panel-right":
            editor_x, tree_x = 0, W - tree_w
        else:
            tree_x, editor_x = 0, tree_w
        for win, x, width in (
            (tree_win, tree_x, tree_w),
            (editor_win, editor_x, editor_w),
        ):
            win.maximized = False
            win.styles.offset = Offset(x, 0)
            win.styles.width = width
            win.styles.height = H
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/fm/test_project_view.py -k layout -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add tyui/app.py tests/fm/test_project_view.py
git commit -m "feat(project-view): _layout_project_view geometry + state field

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `action_project_view` — entry from a file panel

**Files:**
- Modify: `tyui/app.py` (add `action_project_view`, `_project_view_from_panel`, `_window_of`)
- Test: `tests/fm/test_project_view.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/fm/test_project_view.py`:

```python
def _focus_panel_on_file(app, panel_id, file_path):
    """Focus a panel and put its cursor on `file_path`. Returns the FilePanel."""
    win = app.desktop.query_one(f"#{panel_id}", Window)
    panel = win.content
    app.desktop.focus_window(win)
    app.set_focus(panel)
    idx = next(i for i, e in enumerate(panel.entries) if e.path == file_path)
    panel.cursor = idx
    return panel


async def test_f2_in_left_panel_opens_project_view(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f)

        app.action_project_view()
        await _settle(pilot)

        left = app.desktop.query_one("#panel-left", Window)
        right = app.desktop.query_one("#panel-right", Window)
        editors = _editor_windows(app)
        assert len(editors) == 1
        editor = editors[0]
        W, _ = app.desktop.usable_size
        tree_w = max(8, W // 4)
        # Tree docked left at 1/4, editor fills the rest, right panel hidden.
        assert left.region.x == 0
        assert left.region.width == tree_w
        assert editor.region.x == tree_w
        assert right not in app.desktop.windows
        assert right in app.desktop.hidden_windows
        assert app._project_tree_panel_id == "panel-left"
        assert app.desktop.focused_window is editor


async def test_f2_in_right_panel_docks_tree_right(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-right", f)

        app.action_project_view()
        await _settle(pilot)

        left = app.desktop.query_one("#panel-left", Window)
        right = app.desktop.query_one("#panel-right", Window)
        editor = _editor_windows(app)[0]
        W, _ = app.desktop.usable_size
        tree_w = max(8, W // 4)
        assert right.region.width == tree_w
        assert right.region.x == W - tree_w
        assert editor.region.x == 0
        assert left not in app.desktop.windows
        assert app._project_tree_panel_id == "panel-right"


async def test_f2_minimizes_existing_editor(tmp_path):
    f1 = tmp_path / "a.py"
    f1.write_text("a = 1\n")
    f2 = tmp_path / "b.py"
    f2.write_text("b = 2\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f1)
        app.action_project_view()
        await _settle(pilot)
        first_editor = _editor_windows(app)[0]

        # Second F2 on a different file: the first editor goes to the tray.
        _focus_panel_on_file(app, "panel-left", f2)
        app.action_project_view()
        await _settle(pilot)

        assert first_editor in app.desktop.minimized_windows
        editors = _editor_windows(app)
        assert len(editors) == 1
        assert editors[0] is not first_editor
        assert app.desktop.focused_window is editors[0]


async def test_f2_on_directory_is_noop(tmp_path):
    (tmp_path / "subdir").mkdir()
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", tmp_path / "subdir")

        app.action_project_view()
        await _settle(pilot)

        assert _editor_windows(app) == []
        assert app._project_tree_panel_id is None
        assert app.desktop.query_one("#panel-right", Window) in app.desktop.windows
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fm/test_project_view.py -k "panel or minimizes or directory" -v`
Expected: FAIL — `AttributeError: 'TyuiApp' object has no attribute 'action_project_view'`.

- [ ] **Step 3: Implement the action and the panel entry**

Add these methods to `TyuiApp` (place near `_open_editor_window`, ~line 1726):

```python
    def _window_of(self, content) -> Window | None:
        """Walk up from a WindowContent to its enclosing Window (or None)."""
        node = getattr(content, "parent", None)
        while node is not None and not isinstance(node, Window):
            node = getattr(node, "parent", None)
        return node

    def action_project_view(self) -> None:
        """F2: enter Project View. Branches on whether an editor or panel is focused."""
        if self._has_active_modal():
            return
        if self.desktop is None:
            return
        if self._is_editor_focused():
            self._project_view_from_editor()
            return
        panel = self._active_panel()
        if panel is not None:
            self._project_view_from_panel(panel)

    def _project_view_from_panel(self, panel) -> None:
        from tyui.fm.file_panel import FilePanel
        if not isinstance(panel, FilePanel):
            return
        tree_win = self._window_of(panel)
        if tree_win is None or tree_win.id not in ("panel-left", "panel-right"):
            return
        if not (0 <= panel.cursor < len(panel.entries)):
            return
        entry = panel.entries[panel.cursor]
        if entry.is_dir:
            return  # F2 on a directory is a no-op, mirroring F4.
        tree_id = tree_win.id
        other_id = "panel-right" if tree_id == "panel-left" else "panel-left"
        # Hide the opposite panel.
        try:
            other = self.desktop.query_one(f"#{other_id}", Window)
            if other in self.desktop.windows:
                self.desktop.hide_window(other)
        except Exception:
            pass
        # Minimize any currently-open editor windows to the IconTray.
        for w in list(self.desktop.windows):
            if isinstance(w.content, EditorContent):
                self.desktop.minimize_window(w)
        # Build a fresh, NON-maximized editor for the selected file.
        self._editor_seq += 1
        try:
            text = entry.path.read_text()
        except OSError:
            text = ""
        W, H = self.desktop.usable_size
        editor_win = self._make_editor_window(
            entry.path,
            position=(0, 0),
            size=(max(3, W), max(3, H)),
            win_id=f"editor-{self._editor_seq}",
            text=text,
        )
        self.desktop.add_window(editor_win)
        self._project_tree_panel_id = tree_id
        self._layout_project_view(tree_win=tree_win, editor_win=editor_win)
        self.desktop.focus_window(editor_win)
```

(`_project_view_from_editor` is added in Task 3; calling F2 from a panel does not
reach it, so these tests pass without it. If your harness requires the method to
exist for the editor branch, Task 3 adds it — these panel tests never take that
branch.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fm/test_project_view.py -k "panel or minimizes or directory" -v`
Expected: PASS (4 tests). The `layout` tests still pass too.

- [ ] **Step 5: Commit**

```bash
git add tyui/app.py tests/fm/test_project_view.py
git commit -m "feat(project-view): F2 enters Project View from a file panel

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `_project_view_from_editor` — entry from the editor

**Files:**
- Modify: `tyui/app.py` (add `_project_view_from_editor`)
- Test: `tests/fm/test_project_view.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/fm/test_project_view.py`:

```python
async def test_f2_in_editor_reveals_left_tree(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a = 1\n")
    app = TyuiApp(launch_mode="editor", initial_path=str(f))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        editor = _editor_windows(app)[0]
        app.desktop.focus_window(editor)
        await _settle(pilot)

        app.action_project_view()
        await _settle(pilot)

        left = app.desktop.query_one("#panel-left", Window)
        right = app.desktop.query_one("#panel-right", Window)
        W, _ = app.desktop.usable_size
        tree_w = max(8, W // 4)
        # Default tree is panel-left, docked left at 1/4; editor fills the 3/4.
        assert left in app.desktop.windows
        assert left.region.x == 0
        assert left.region.width == tree_w
        assert editor.region.x == tree_w
        assert right not in app.desktop.windows
        assert app._project_tree_panel_id == "panel-left"


async def test_f2_in_editor_uses_remembered_tree_side(tmp_path):
    f1 = tmp_path / "a.py"
    f1.write_text("a = 1\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        # Enter Project View from the RIGHT panel so the tree side is remembered.
        _focus_panel_on_file(app, "panel-right", f1)
        app.action_project_view()
        await _settle(pilot)
        editor = _editor_windows(app)[0]
        app.desktop.focus_window(editor)
        await _settle(pilot)

        # F2 from the editor re-docks using the remembered right side.
        app.action_project_view()
        await _settle(pilot)

        right = app.desktop.query_one("#panel-right", Window)
        W, _ = app.desktop.usable_size
        tree_w = max(8, W // 4)
        assert right.region.x == W - tree_w
        assert editor.region.x == 0
        assert app._project_tree_panel_id == "panel-right"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_project_view.py -k editor -v`
Expected: FAIL — editor branch is a no-op (method missing) so the panel never
reveals / geometry assertions fail, or `AttributeError` if referenced.

- [ ] **Step 3: Implement `_project_view_from_editor`**

Add to `TyuiApp` right after `_project_view_from_panel`:

```python
    def _project_view_from_editor(self) -> None:
        from tyui.fm.file_panel import FilePanel
        editor_win = self.desktop.focused_window
        if editor_win is None or not isinstance(editor_win.content, EditorContent):
            return
        tree_id = self._project_tree_panel_id or "panel-left"
        other_id = "panel-right" if tree_id == "panel-left" else "panel-left"
        try:
            tree_win = self.desktop.query_one(f"#{tree_id}", Window)
        except Exception:
            return
        if not isinstance(tree_win.content, FilePanel):
            return
        if tree_win not in self.desktop.windows:
            self.desktop.show_window(tree_win)
        try:
            other = self.desktop.query_one(f"#{other_id}", Window)
            if other in self.desktop.windows:
                self.desktop.hide_window(other)
        except Exception:
            pass
        self._project_tree_panel_id = tree_id
        self._layout_project_view(tree_win=tree_win, editor_win=editor_win)
        self.desktop.focus_window(editor_win)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/fm/test_project_view.py -k editor -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tyui/app.py tests/fm/test_project_view.py
git commit -m "feat(project-view): F2 enters Project View from the editor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Register F2 commands + clear state on exit

**Files:**
- Modify: `tyui/fm/file_panel.py:794-804` (add `panel.project_view`)
- Modify: `tyui/app.py` (`_FocusableEditorContent.get_commands` override; `_toggle_panel` clears state)
- Test: `tests/fm/test_project_view.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/fm/test_project_view.py`:

```python
async def test_f2_commands_registered(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a = 1\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f)
        await _settle(pilot)
        cmd = app.command_registry.get("panel.project_view")
        assert cmd is not None
        assert cmd.hotkey == "f2"


async def test_f2_hotkey_routes_from_panel(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a = 1\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f)
        await _settle(pilot)

        await pilot.press("f2")
        await _settle(pilot)

        assert len(_editor_windows(app)) == 1
        assert app._project_tree_panel_id == "panel-left"


async def test_toggle_panel_clears_project_view_state(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a = 1\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f)
        app.action_project_view()
        await _settle(pilot)
        assert app._project_tree_panel_id == "panel-left"

        # Ctrl+1 / Ctrl+2 (the exit path) clears Project View state.
        app._toggle_panel("panel-right")
        await _settle(pilot)
        assert app._project_tree_panel_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/fm/test_project_view.py -k "registered or routes or clears" -v`
Expected: FAIL — `panel.project_view` not registered; `_toggle_panel` doesn't
clear the field.

- [ ] **Step 3a: Add the panel command**

In `tyui/fm/file_panel.py`, inside the list returned by `get_commands()` (after
the `panel.new` entry, around line 795), add:

```python
            WindowCommand(id="panel.project_view", label="Project View", handler=_bind("project_view"), hotkey="f2"),
```

- [ ] **Step 3b: Add the editor command (app layer)**

In `tyui/app.py`, add a `get_commands` override to `_FocusableEditorContent`
(after its `focus` method, ~line 105):

```python
    def get_commands(self):
        commands = super().get_commands()
        app = getattr(self, "app", None)
        handler = getattr(app, "action_project_view", None)
        if callable(handler):
            commands.append(
                WindowCommand(
                    id="project_view", label="Project View",
                    handler=handler, hotkey="f2",
                )
            )
        return commands
```

(`WindowCommand` is already imported at `tyui/app.py:72`, so no local import is
needed.)

- [ ] **Step 3c: Clear state in `_toggle_panel`**

In `tyui/app.py`, at the top of `_toggle_panel` (after the `if self.desktop is
None: return` guard, ~line 1162), add:

```python
        # Toggling a panel is the Project View exit path.
        self._project_tree_panel_id = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/fm/test_project_view.py -k "registered or routes or clears" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tyui/app.py tyui/fm/file_panel.py tests/fm/test_project_view.py
git commit -m "feat(project-view): register F2 commands; Ctrl+1/2 clears state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Preserve the split across terminal resize

**Files:**
- Modify: `tyui/app.py` (`_relayout_after_resize`, ~line 537)
- Test: `tests/fm/test_project_view.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/fm/test_project_view.py`:

```python
@pytest.mark.parametrize("width,height", [(160, 50), (70, 20)])
async def test_project_view_survives_resize(tmp_path, width, height):
    f = tmp_path / "a.py"
    f.write_text("a = 1\n")
    app = TyuiApp(launch_mode="fm", initial_path=str(tmp_path))
    async with app.run_test(size=(100, 30)) as pilot:
        await _settle(pilot)
        _focus_panel_on_file(app, "panel-left", f)
        app.action_project_view()
        await _settle(pilot)

        await pilot.resize_terminal(width, height)
        await _settle(pilot)

        left = app.desktop.query_one("#panel-left", Window)
        editor = _editor_windows(app)[0]
        W, _ = app.desktop.usable_size
        tree_w = max(8, W // 4)
        assert left.region.x == 0
        assert left.region.width == tree_w
        assert editor.region.x == tree_w
        assert left.region.width + editor.region.width == W
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/fm/test_project_view.py -k resize -v`
Expected: FAIL — after resize `_relayout_after_resize` calls `_tile_panels`,
which re-tiles the tree panel to half width, breaking the 1/4 split.

- [ ] **Step 3: Branch the resize hook on Project View**

In `tyui/app.py`, replace the body of `_relayout_after_resize` (the
`self._tile_panels()` / cascade block, ~lines 554-559) so Project View wins:

```python
        if self.desktop is None or self.manager is None:
            return
        if self._project_tree_panel_id is not None:
            self._relayout_project_view()
            return
        self._tile_panels()
        # we-mode cascade editor windows must keep filling the desktop too.
        if self._cascade_ids:
            self._apply_cascade_geometry()
```

Then add the helper right after `_relayout_after_resize`:

```python
    def _relayout_project_view(self) -> None:
        """Re-apply the 1/4 tree + 3/4 editor split after a terminal resize."""
        tree_id = self._project_tree_panel_id
        if tree_id is None:
            return
        try:
            tree_win = self.desktop.query_one(f"#{tree_id}", Window)
        except Exception:
            return
        editors = [
            w for w in self.desktop.windows
            if isinstance(w.content, EditorContent)
        ]
        if tree_win not in self.desktop.windows or not editors:
            return
        self._layout_project_view(tree_win=tree_win, editor_win=editors[-1])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/fm/test_project_view.py -k resize -v`
Expected: PASS (2 parametrized cases).

- [ ] **Step 5: Run the full new test file + lint**

Run: `pytest tests/fm/test_project_view.py -v`
Expected: PASS (all tests).
Run: `ruff check tyui/app.py tyui/fm/file_panel.py tests/fm/test_project_view.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add tyui/app.py tests/fm/test_project_view.py
git commit -m "feat(project-view): keep 1/4-3/4 split across terminal resize

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Full regression pass

- [ ] **Step 1: Run the entire suite**

Run: `pytest -q`
Expected: all pass (587 existing + the new Project View tests), no new failures.

- [ ] **Step 2: If anything regresses**, debug with superpowers:systematic-debugging
  before claiming completion. In particular re-check that `_toggle_panel`
  clearing `_project_tree_panel_id` did not disturb the existing
  `test_panel_close_hide.py` expectations (it only adds a field reset).

- [ ] **Step 3: Final commit (only if fixes were needed)**

```bash
git add -A
git commit -m "test(project-view): fix regressions surfaced by full suite

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Final state (1/4 tree side-aware + 3/4 editor, other panel hidden) → Task 1 (geometry) + Tasks 2/3 (entry).
- Entry 1 (F2 in panel, file): tree = clicked panel, hide other, minimize editors, open new editor → Task 2.
- Entry 2 (F2 in editor): editor 3/4, tree 1/4 revealed → Task 3.
- F2 command registration (panel + editor, no double-fire) → Task 4.
- Exit via Ctrl+1 / Ctrl+2 clearing state → Task 4.
- Directory no-op, editor-not-editor bail, resize preservation → Tasks 2, 3, 5.
- Tests enumerated in spec all present across Tasks 1-5.

**Placeholder scan:** No TBD/TODO; every code step shows full code.

**Type/name consistency:** `_project_tree_panel_id`, `_layout_project_view(tree_win, editor_win)`, `action_project_view`, `_project_view_from_panel`, `_project_view_from_editor`, `_relayout_project_view`, `_window_of`, command ids `panel.project_view` / `project_view` are used identically across all tasks. `_make_editor_window` signature matches `tyui/app.py:1686`. `EditorContent` / `FilePanel` / `Window` / `Offset` import sources verified.

**Verified imports:** `WindowCommand` is imported at `tyui/app.py:72`;
`self._editor_seq = 0` is at `tyui/app.py:300`; `self.desktop.on_resized =
self._relayout_after_resize` is at `tyui/app.py:335`.
```
