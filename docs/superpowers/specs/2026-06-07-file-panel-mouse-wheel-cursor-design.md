# File panel: mouse-wheel moves the cursor

Date: 2026-06-07
Status: Design — approved for planning
Area: `tyui/fm/file_panel.py`

## Problem

The file panel (`FilePanel`) has no mouse-wheel handler — scrolling the wheel
over the listing does nothing. Users expect the wheel to move through the file
list. We want the wheel to move the **cursor** (the highlighted row), exactly
like pressing ↑/↓ a few times, and — when scrolling over the inactive panel — to
activate that panel first (like a click).

## Background (current model)

- `self.cursor` — index of the highlighted entry.
- `self.row_offset` — first visible row (scroll position).
- `move_cursor(delta)` — clamps `cursor` to `[0, len(entries)-1]` and calls
  `_ensure_cursor_visible()` to pull `row_offset` so the cursor stays on screen
  (handles both single- and multi-column layouts).
- Keyboard handlers (`action_cursor_up/down`) do `_qs_reset()` → `move_cursor(±1)`
  → `refresh()`.
- A panel is "active" (`_is_active_panel`) when it `has_focus` OR its enclosing
  `Window` is the `Desktop.focused_window`.
- Clicking activates a window via `Window.on_mouse_down` → `Window.FocusRequested`.
  The mouse **wheel** emits `MouseScrollUp/Down`, NOT `MouseDown`, so it does NOT
  trigger that path — activation on scroll must be requested explicitly.
- Precedent: the embedded console's `_BufferView` overrides
  `_on_mouse_scroll_up`/`_on_mouse_scroll_down`. Textual's `Widget._on_mouse_scroll_*`
  no-ops on a non-scrollable widget and lets the event bubble, so the override
  must be on those system-dispatch methods (not `on_mouse_scroll_*`).

## Solution

Add wheel handling to `FilePanel`:

- Module constant `_WHEEL_STEP = 3` (entries moved per wheel notch).
- Override `_on_mouse_scroll_down(self, event)` → `self._wheel(_WHEEL_STEP)`.
- Override `_on_mouse_scroll_up(self, event)` → `self._wheel(-_WHEEL_STEP)`.
- `_wheel(delta)`:
  1. If `not self._is_active_panel`: request focus on the enclosing window
     (`win = self._enclosing_window(); if win is not None: self.post_message(Window.FocusRequested(win))`).
     This funnels through the same path a click uses, so `Desktop.focused_window`,
     F-key routing, and the command-line target all update consistently.
  2. `self._qs_reset()` — match the keyboard cursor handlers (quick-search ends
     when you navigate away).
  3. `self.move_cursor(delta)` — clamps at the list ends; `_ensure_cursor_visible`
     pulls the viewport.
  4. `self.refresh()`.
  5. `event.stop()`.

### Refactor (in-scope)

`_is_active_panel` currently inlines a walk up to the enclosing `Window` and
then the `Desktop`. Extract the "walk up to enclosing `Window`" part into a small
`_enclosing_window() -> Window | None` helper and reuse it from both
`_is_active_panel` and `_wheel`. No behaviour change to `_is_active_panel`.

### Multi-column layouts

In Brief/Medium (column-major) view, `move_cursor(±3)` advances 3 entries down
the column order, which `_ensure_cursor_visible` already scrolls correctly. No
special-casing needed.

## Data flow

```
wheel notch -> _on_mouse_scroll_down/up
            -> _wheel(±3)
               -> (if inactive) post Window.FocusRequested(enclosing window)
               -> _qs_reset()
               -> move_cursor(±3)  -> _ensure_cursor_visible() adjusts row_offset
               -> refresh(); event.stop()
```

## Testing

Async tests (mirroring `tests/fm/console/test_window.py::test_mouse_wheel_scrolls_buffer`,
which posts `events.MouseScrollUp/Down`):

- ScrollDown over a panel with many entries moves `cursor` by +3; a following
  ScrollUp moves it back by 3.
- Clamping: ScrollUp at the top is a no-op (cursor stays 0, no crash); ScrollDown
  at the bottom clamps at `len(entries)-1`.
- Activation: scrolling over the **inactive** panel makes it active
  (`_is_active_panel` True / its window becomes `Desktop.focused_window`) before/while
  moving the cursor.
- Empty directory and single-entry directory: wheel does not crash and does not
  move the cursor out of range.

## Out of scope

- Keyboard navigation, click handling, multi-column layout logic (unchanged).
- The embedded console (`_BufferView`) — already has its own wheel handling.
- Horizontal wheel / shift-wheel.
