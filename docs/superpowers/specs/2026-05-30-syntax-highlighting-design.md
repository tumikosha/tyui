# Syntax Highlighting — Design

Date: 2026-05-30
Status: Approved (design), pending implementation plan

## Goal

Add per-language syntax highlighting to the embeddable editor (`EditorWidget` /
`EditorContent`). Highlighting is a **base style layer**; the existing overlays
(folds, search, selection, cursor) compose on top of it without regression.

## Decisions (from brainstorming)

| Topic | Decision |
|-------|----------|
| Engine | **Pygments** (already a dependency; hundreds of languages, lexer-by-filename + guess) |
| Recompute model | **Per-line span cache + debounce** — tokenize the whole buffer, cache spans per line, recompute on a short delay after edits |
| Large files | **Size threshold + background thread** — auto-disable above threshold; below threshold tokenize in a worker and marshal back to the UI thread |
| Color granularity | **Base set (~8–10 roles)** — collapse Pygments token hierarchy to a small role set |
| User control | **Toggle command in Editor menu (Ctrl+H)** + **manual language picker** |

## Architecture (Approach A)

A separate, editor-agnostic highlighter module owns tokenization. `EditorWidget`
holds the highlighter plus a per-buffer-line span cache and composes the spans
into the rendered line.

### 1. `tyui/windowing/core/highlight.py` (new, editor-agnostic)

No Textual/rich imports — pure Pygments + stdlib, so it unit-tests directly.

- `Span` — dataclass `(start: int, end: int, role: str)` in **buffer-column**
  coordinates. `role` is the already-collapsed base role (see §3), never a raw
  Pygments token.
- `class SyntaxHighlighter`:
  - `set_language(lexer_name: str | None)` — manual override; `None` restores
    auto-detection.
  - `detect(file_path: str | None, sample_text: str) -> None` — resolve a lexer
    via Pygments `get_lexer_for_filename`, fall back to `guess_lexer` on the
    sample; if nothing matches, the highlighter becomes a no-op (empty spans).
  - `tokenize(lines: list[str]) -> list[list[Span]]` — run the full text
    through the active lexer, then split tokens that span newlines into
    per-line `Span`s. Returns one list per input line (empty list = no
    highlight). Unknown/no lexer → list of empty lists.
  - `enabled` / `language_name` introspection for status display.

### 2. Token → role mapping

A table mapping Pygments token types to base roles, using the Pygments token
hierarchy (`token in Keyword` → `keyword`, etc.) so subtypes collapse upward.
Anything unmatched → no role (default text color).

Base roles: `keyword, name, function, class, string, number, comment,
operator, builtin, error`.

### 3. Palette roles (in `tyui/windowing/themes/modern_dark.py`)

Add `editor.syntax.<role>` for each base role:
`editor.syntax.keyword`, `.name`, `.function`, `.class`, `.string`,
`.number`, `.comment`, `.operator`, `.builtin`, `.error`.

`Theme.resolve` already walks `editor.syntax.keyword → editor.syntax → editor
→ ""`, so themes that omit these roles simply render no highlight (graceful
degradation). Color choices target a 256-color terminal; keep them readable
against the existing `editor` background.

### 4. `EditorWidget` integration

New state:

- `self._highlighter: SyntaxHighlighter | None`
- `self._syntax_spans: list[list[Span]]` — cache keyed by buffer row
- `self._highlight_enabled: bool` (default `True`)
- a dirty flag + a debounce timer handle

Recompute flow:

- On buffer change (`_post_buffer_update`), mark the cache dirty and (re)arm a
  debounce timer via `set_timer` (cancel any pending one).
- When the timer fires: if the buffer byte size is below
  `_SYNTAX_SIZE_THRESHOLD` (module constant, ~1 MiB, mirroring
  `_HEX_VIEW_SIZE_THRESHOLD`), run `tokenize` in a worker thread and marshal the
  result back with `self.call_from_thread(...)` (the `_run_copy_move` pattern),
  then `refresh()`. At/above the threshold, disable highlighting and skip.
- Initial tokenization runs on `on_mount` (after `detect`).

Rendering — **`render_line` refactor to a single compositing model**:

- Build a priority-ordered list of spans for the rendered line:
  `syntax (lowest) < fold placeholder < search match < selection < cursor
  (highest)`.
- Syntax spans are mapped from buffer-column to rendered-column with the same
  `_buffer_col_to_rendered_col` translation selection already uses, so folds
  stay correct. Inside a collapsed placeholder the `fold_marker` style wins
  because it has higher priority.
- A single pass over the line picks, for each position, the style of the
  highest-priority span covering it. This replaces the current three branches
  (selection-on-line / cursor-on-line / plain) with one path, removing
  duplication.
- When highlighting is disabled or spans are empty, the base layer is plain
  text — behavior identical to today.

### 5. User control

- **Toggle:** `EditorContent.get_commands()` publishes a `WindowCommand`
  ("Syntax Highlight", id e.g. `editor.toggle_syntax`) bound to **Ctrl+H**. It
  flips `_highlight_enabled` and refreshes.
  - **Known risk:** many terminals send the same byte (0x08) for Ctrl+H and
    Backspace, which could collide with the existing `backspace` binding in
    `EditorWidget.BINDINGS`. Implementation must verify Ctrl+H is distinguished
    from Backspace in this Textual version; if not, the toggle falls back to a
    menu-only command (and/or an alternate key). Resolve during implementation.
- **Manual language picker:** a command ("Set Language…") opens a selection
  dialog following the `dialogs.py` pattern (typed `context` payload, `*.Result`
  message). The dialog lists Pygments lexer names; selecting one calls
  `set_language(...)` and triggers a recompute. Auto-detection remains the
  default.

## Testing

- `tests/windowing/test_highlight.py` (unit, pure logic):
  - tokenize Python and JSON → expected role spans on representative lines
  - token→role mapping collapses subtypes correctly
  - `detect` by filename (`.py`, `.json`) and `guess_lexer` fallback
  - unknown language → all-empty spans (no-op)
  - threshold behavior: above threshold → highlighting disabled
- Async smoke (editor shell):
  - highlighting does not break selection / search / cursor / fold rendering
    (compositing priority order)
  - toggle on/off changes rendering and restores plain text
  - switching language via the picker recomputes spans

## Out of scope (YAGNI for now)

- Incremental/visible-region-only tokenization (tree-sitter-style)
- Detailed 20+ role palette and per-language theme tuning
- Highlighting in the F3 read-only viewer (editor only for this iteration)
- Persisting per-file language choice across sessions
