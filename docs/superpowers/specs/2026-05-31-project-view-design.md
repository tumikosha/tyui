# Project View (F2) — Design Spec

**Date:** 2026-05-31
**Branch:** `feature/project-view`
**Status:** Approved (pending spec review)

## Summary

Add an IDE-style "Project View" layout toggled by **F2**: one file panel acts as a
narrow project tree (1/4 of the desktop) docked on its own side, with the text
editor for the selected file filling the remaining 3/4. Both entry points
(F2 in a file panel, F2 in the editor) converge on the same family of layouts.

## Final State

The tree panel keeps the side it already lives on (`panel-left` → left slot,
`panel-right` → right slot). The editor takes the remaining 3/4. The *other*
file panel is hidden.

```
F2 in LEFT panel:                 F2 in RIGHT panel:
+------+----------------+        +----------------+------+
| tree |                |        |                | tree |
| 1/4  |   editor 3/4   |        |   editor 3/4   | 1/4  |
+------+----------------+        +----------------+------+
(panel-right hidden)            (panel-left hidden)
        IconTray: [1 old-editor] [2 ...]   (previously-open editors)
```

## Geometry

New method `TyuiApp._layout_project_view(tree_win, editor_win)`:

- `W, H = self.desktop.usable_size`; bail if `W <= 0 or H <= 0`.
- `tree_w = max(8, W // 4)`.
- Tree side is derived from the tree window id:
  - `panel-left` (left side): tree at `offset=(0, 0)`, `width=tree_w`;
    editor at `offset=(tree_w, 0)`, `width=W - tree_w`.
  - `panel-right` (right side): editor at `offset=(0, 0)`, `width=W - tree_w`;
    tree at `offset=(W - tree_w, 0)`, `width=tree_w`.
- Both windows get `height=H`, `offset.y=0`.
- The console-bottom split in `_tile_panels` does **not** apply in Project View;
  the editor and tree fill the full usable height.

This method is also invoked from the existing desktop-resize relayout hook
(the same path that calls `_tile_panels` today) when Project View is active, so
the 1/4 ÷ 3/4 split survives terminal resize.

## State

One new field on `TyuiApp`:

- `self._project_tree_panel_id: str | None` — id of the panel currently serving
  as the project tree (`"panel-left"` / `"panel-right"`), or `None` when Project
  View is not active. Set on entry; used by the resize relayout hook and by the
  editor entry point to pick the tree side. Cleared when a panel is re-toggled
  via Ctrl+1 / Ctrl+2 (existing `_toggle_panel`), which is also the exit path.

## Entry Point 1 — F2 in a file panel (on a file)

`app.action_project_view()` when the active context is a `FilePanel`:

1. Modal gate: `if self._has_active_modal(): return` (every action_* does this).
2. Resolve the active panel via `self._active_panel()`. If none, bail.
3. If the cursor is on a directory (`entry.is_dir`) → no-op (mirrors `action_edit`).
4. `tree_win` = the active panel's `Window`; `tree_id = tree_win.id`.
5. Hide the *other* panel: `self.desktop.hide_window(other_panel_win)` (the panel
   whose id is not `tree_id`), if it is currently visible.
6. Minimize every currently-open editor window to the IconTray:
   `for w in editor_windows: self.desktop.minimize_window(w)`.
   (Editor windows = visible `desktop.windows` whose `content` is an
   `EditorContent`.)
7. Build a fresh editor for the file under the cursor via the existing
   `_open_editor_window(path, read_only=False)` factory path — but mounted
   *not maximized* (Project View sizes it explicitly), then
   `_layout_project_view(tree_win, editor_win)`.
8. Record `self._project_tree_panel_id = tree_id`. Focus the editor.

## Entry Point 2 — F2 in the editor

`app.action_project_view()` when the active context is an `EditorContent`:

1. Modal gate.
2. `editor_win` = the focused editor `Window`
   (`self.desktop.focused_window`); if it is not an editor window, bail.
3. `tree_id = self._project_tree_panel_id or "panel-left"`.
4. `tree_win = query_one(f"#{tree_id}", Window)`. If hidden,
   `self.desktop.show_window(tree_win)`. Hide the other panel if visible.
5. `_layout_project_view(tree_win, editor_win)` — editor to its 3/4 side, tree to
   its 1/4 side.
6. Record `self._project_tree_panel_id = tree_id`.

## Command Registration

F2 is currently **unbound** (file-panel keymap only carries a cosmetic
"UsrMnu" label at F2; the editor has no F2 binding), so there is no conflict.

- **File panel:** add a `WindowCommand(id="panel.project_view", label="Project View",
  hotkey="f2", handler=…)` to `FilePanel.get_commands()`. The handler delegates to
  `app.action_project_view` exactly like the other panel F-keys
  (`getattr(app, "action_project_view", None)`).
- **Editor:** add a `WindowCommand(id="project_view", label="Project View",
  hotkey="f2", handler=…)` to `EditorContent.get_commands()`, delegating to the
  same `app.action_project_view`.

Both routes call the single `action_project_view`, which branches on the active
context (`_active_panel()` returns a panel → entry 1; otherwise the focused
window is an editor → entry 2).

Because F-keys are panel/editor-scoped (not app `BINDINGS`), no double-firing
risk per the project's F-key convention.

## Exit

No dedicated exit command (YAGNI). Project View is left by re-toggling a panel
with the existing **Ctrl+1 / Ctrl+2** (`_toggle_panel`) or by maximizing the
editor. `_toggle_panel` clears `_project_tree_panel_id`.

## Edge Cases

- F2 on a directory in a panel → no-op.
- F2 in the editor when its window is not actually an `EditorContent` → bail.
- F2 in a panel with no open editors → step 6 is a no-op; a fresh editor opens.
- Re-pressing F2 in a panel while already in Project View → the current editor is
  minimized to tray and a new editor opens for the (possibly different) selected
  file. This is the intended "stack of opened files" behaviour.
- Desktop resize while in Project View → relayout hook re-applies
  `_layout_project_view` using `_project_tree_panel_id`.

## Tests — `tests/fm/test_project_view.py` (async smoke)

1. F2 in left panel on a file → tree window at left 1/4, editor at right 3/4,
   `panel-right` in `desktop.hidden_windows`.
2. F2 in right panel on a file → `panel-right` is the tree at right 1/4, editor at
   left 3/4, `panel-left` hidden.
3. F2 with an editor already open → the prior editor is in
   `desktop.minimized_windows`; the new editor is `desktop.focused_window`.
4. F2 in the editor → editor occupies its 3/4 side, `panel-left` (default tree)
   visible at 1/4.
5. F2 on a directory entry → layout unchanged (no new window, panels untouched).
6. Desktop resize after entering Project View → 1/4 ÷ 3/4 split preserved.

## Non-Goals

- No persistence of Project View across launches.
- No multi-editor tabbing; minimized editors live in the existing IconTray.
- No new exit hotkey; reuse Ctrl+1 / Ctrl+2 and maximize.
