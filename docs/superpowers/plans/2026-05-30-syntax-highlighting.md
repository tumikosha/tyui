# Syntax Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-language syntax highlighting to the embeddable editor, rendered as a base style layer beneath the existing fold/search/selection/cursor overlays.

**Architecture:** A new editor-agnostic `SyntaxHighlighter` (Pygments) produces per-buffer-line style spans. `EditorWidget` caches those spans, recomputes them on a debounce in a worker thread (auto-disabling above a size threshold), and `render_line` composites all style layers by priority. A toggle command (Ctrl+H) and a manual language picker give the user control.

**Tech Stack:** Python ≥3.12, Pygments 2.20, Textual 8.2, rich 15, pytest (asyncio auto mode).

---

## File Structure

- **Create** `tyui/windowing/core/highlight.py` — `Span` dataclass, Pygments-token→role mapping, `SyntaxHighlighter` (detect / set_language / tokenize). No Textual/rich imports; pure logic.
- **Modify** `tyui/windowing/themes/modern_dark.py` — add `editor.syntax.<role>` palette styles.
- **Modify** `tyui/windowing/editor/widget.py` — highlighter state, debounce + worker recompute, size-threshold gate, `render_line` compositing refactor, `set_language` / `set_highlight_enabled`.
- **Modify** `tyui/windowing/editor/content.py` — `Syntax Highlight` toggle command (Ctrl+H) and `Set Language...` command.
- **Modify** `tyui/app.py` — `SetLanguageRequest` context + `action_set_language` modal flow + handler branch in `on_input_dialog_submitted`.
- **Create** `tests/windowing/test_highlight.py` — unit tests for the highlighter.
- **Create** `tests/windowing/test_editor_highlight.py` — async smoke tests for editor integration, toggle, language picker, overlay compositing.

---

## Task 1: SyntaxHighlighter core module

**Files:**
- Create: `tyui/windowing/core/highlight.py`
- Test: `tests/windowing/test_highlight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/windowing/test_highlight.py
from tyui.windowing.core.highlight import SyntaxHighlighter, Span, token_to_role


def test_detect_by_filename_python():
    h = SyntaxHighlighter()
    h.detect("foo.py", "x = 1\n")
    assert h.enabled
    assert "Python" in h.language_name


def test_unknown_language_is_noop():
    h = SyntaxHighlighter()
    h.detect("foo.unknownext", "")
    assert not h.enabled
    assert h.tokenize(["anything", "here"]) == [[], []]


def test_tokenize_python_keyword_and_string():
    h = SyntaxHighlighter()
    h.detect("foo.py", "")
    spans = h.tokenize(["def f():", "    return 'hi'"])
    roles_line0 = {s.role for s in spans[0]}
    roles_line1 = {s.role for s in spans[1]}
    assert "keyword" in roles_line0          # `def`
    assert "function" in roles_line0         # `f`
    assert "keyword" in roles_line1          # `return`
    assert "string" in roles_line1           # 'hi'
    # spans stay within their own line's column range
    for s in spans[1]:
        assert 0 <= s.start <= s.end <= len(spans and "    return 'hi'")


def test_tokenize_preserves_line_count_and_blank_lines():
    h = SyntaxHighlighter()
    h.detect("foo.py", "")
    lines = ["x = 1", "", "y = 2"]
    spans = h.tokenize(lines)
    assert len(spans) == 3
    assert spans[1] == []  # blank line, no spans


def test_set_language_override():
    h = SyntaxHighlighter()
    h.detect("foo.txt", "")          # likely Text lexer / no useful tokens
    h.set_language("json")
    assert h.enabled
    spans = h.tokenize(['{"a": 1}'])
    assert any(s.role in {"string", "number", "name"} for s in spans[0])


def test_token_to_role_collapses_subtypes():
    from pygments.token import Keyword, Name, Comment
    assert token_to_role(Keyword.Namespace) == "keyword"
    assert token_to_role(Name.Function) == "function"
    assert token_to_role(Comment.Single) == "comment"
    assert token_to_role(Name) == "name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_highlight.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tyui.windowing.core.highlight'`

- [ ] **Step 3: Write minimal implementation**

```python
# tyui/windowing/core/highlight.py
"""Pygments-backed syntax tokenizer producing per-line style spans.

Editor-agnostic: no Textual/rich imports. Maps the Pygments token hierarchy
down to a small set of base roles consumed by the palette as
``editor.syntax.<role>``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pygments.lexer import Lexer
from pygments.lexers import get_lexer_by_name, get_lexer_for_filename, guess_lexer
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    _TokenType,
)
from pygments.util import ClassNotFound


@dataclass(frozen=True)
class Span:
    """A styled run on a single buffer line, in buffer-column coordinates."""

    start: int
    end: int
    role: str


def token_to_role(tok: _TokenType) -> str | None:
    """Collapse a Pygments token type to a base role, or None for default text.

    Order matters: Name subtypes are checked before generic Name.
    """
    if tok in Comment:
        return "comment"
    if tok in String:
        return "string"
    if tok in Number:
        return "number"
    if tok in Keyword:
        return "keyword"
    if tok in Name.Function:
        return "function"
    if tok in Name.Class:
        return "class"
    if tok in Name.Builtin:
        return "builtin"
    if tok in Name:
        return "name"
    if tok in Operator:
        return "operator"
    if tok in Error:
        return "error"
    return None


class SyntaxHighlighter:
    """Resolves a lexer (auto or manual) and tokenizes buffer lines to spans."""

    def __init__(self) -> None:
        self._auto_lexer: Lexer | None = None
        self._user_lexer: Lexer | None = None

    @property
    def _active_lexer(self) -> Lexer | None:
        return self._user_lexer or self._auto_lexer

    @property
    def enabled(self) -> bool:
        return self._active_lexer is not None

    @property
    def language_name(self) -> str:
        lex = self._active_lexer
        return lex.name if lex is not None else ""

    def detect(self, file_path: str | None, sample_text: str) -> None:
        """Pick a lexer by filename, falling back to content guessing."""
        self._user_lexer = None
        lexer: Lexer | None = None
        if file_path:
            try:
                lexer = get_lexer_for_filename(file_path)
            except ClassNotFound:
                lexer = None
        if lexer is None and sample_text.strip():
            try:
                lexer = guess_lexer(sample_text)
            except ClassNotFound:
                lexer = None
        self._auto_lexer = self._configure(lexer)

    def set_language(self, name: str | None) -> None:
        """Set a manual lexer override by Pygments name/alias, or clear it."""
        if not name:
            self._user_lexer = None
            return
        try:
            self._user_lexer = self._configure(get_lexer_by_name(name))
        except ClassNotFound:
            pass  # keep the current override / auto lexer

    @staticmethod
    def _configure(lexer: Lexer | None) -> Lexer | None:
        if lexer is not None:
            # Keep blank lines so token rows line up 1:1 with buffer rows.
            lexer.stripnl = False
            lexer.stripall = False
        return lexer

    def tokenize(self, lines: list[str]) -> list[list[Span]]:
        """Return one list of Spans per input line (empty list = no highlight)."""
        result: list[list[Span]] = [[] for _ in lines]
        lexer = self._active_lexer
        if lexer is None:
            return result
        text = "\n".join(lines)
        row = 0
        col = 0
        for tok, value in lexer.get_tokens(text):
            role = token_to_role(tok)
            parts = value.split("\n")
            for k, part in enumerate(parts):
                if k > 0:
                    row += 1
                    col = 0
                if part and role and row < len(result):
                    result[row].append(Span(col, col + len(part), role))
                col += len(part)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/windowing/test_highlight.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/core/highlight.py tests/windowing/test_highlight.py
git commit -m "feat(editor): add Pygments-backed SyntaxHighlighter core"
```

---

## Task 2: Palette roles for syntax

**Files:**
- Modify: `tyui/windowing/themes/modern_dark.py` (the `editor.*` block near line 45-52)
- Test: `tests/windowing/test_highlight.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/windowing/test_highlight.py
def test_palette_has_syntax_roles():
    from tyui.windowing.themes.modern_dark import modern_dark
    for role in (
        "keyword", "name", "function", "class", "string",
        "number", "comment", "operator", "builtin", "error",
    ):
        style = modern_dark.resolve(f"editor.syntax.{role}")
        assert style.fg is not None, f"editor.syntax.{role} has no colour"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_highlight.py::test_palette_has_syntax_roles -v`
Expected: FAIL — `resolve` falls back to empty `Style()` whose `fg is None`.

- [ ] **Step 3: Write minimal implementation**

In `tyui/windowing/themes/modern_dark.py`, add these entries inside the `styles` dict, right after the `"editor.line_numbers"` line:

```python
        # Editor — syntax highlighting (base roles)
        "editor.syntax.keyword":       Style(fg="#c586c0"),
        "editor.syntax.name":          Style(fg="#9cdcfe"),
        "editor.syntax.function":      Style(fg="#dcdcaa"),
        "editor.syntax.class":         Style(fg="#4ec9b0"),
        "editor.syntax.string":        Style(fg="#ce9178"),
        "editor.syntax.number":        Style(fg="#b5cea8"),
        "editor.syntax.comment":       Style(fg="#6a9955", italic=True),
        "editor.syntax.operator":      Style(fg="#d4d4d4"),
        "editor.syntax.builtin":       Style(fg="#4ec9b0"),
        "editor.syntax.error":         Style(fg="#f44747"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/windowing/test_highlight.py::test_palette_has_syntax_roles -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/themes/modern_dark.py tests/windowing/test_highlight.py
git commit -m "feat(editor): add editor.syntax.* palette roles"
```

---

## Task 3: Wire SyntaxHighlighter into EditorWidget

**Files:**
- Modify: `tyui/windowing/editor/widget.py` (imports near line 19-23; `__init__` line 89-112; `on_mount` line 136-138; `_post_buffer_update` line 451-455)
- Test: `tests/windowing/test_editor_highlight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/windowing/test_editor_highlight.py
import pytest

from textual.app import App, ComposeResult

from tyui.windowing.editor.widget import EditorWidget
from tyui.windowing.core.buffer import TextBuffer


class _Host(App):
    def __init__(self, text: str, path: str) -> None:
        super().__init__()
        self._buf = TextBuffer.from_string(text)
        self._buf.file_path = path

    def compose(self) -> ComposeResult:
        yield EditorWidget(buffer=self._buf)


async def test_editor_populates_syntax_spans_for_python():
    app = _Host("def f():\n    return 1\n", "foo.py")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        # Spans cached for the buffer; first line carries a keyword span.
        assert editor._syntax_spans, "no syntax spans computed"
        roles = {s.role for s in editor._syntax_spans[0]}
        assert "keyword" in roles


async def test_editor_no_spans_for_unknown_language():
    app = _Host("just some text\n", "notes.unknownext")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        assert all(not row for row in editor._syntax_spans) or editor._syntax_spans == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_editor_highlight.py -v`
Expected: FAIL — `AttributeError: 'EditorWidget' object has no attribute '_syntax_spans'`

- [ ] **Step 3: Write minimal implementation**

In `tyui/windowing/editor/widget.py`:

(a) Add the import near the other core imports (after line 22):

```python
from tyui.windowing.core.highlight import Span, SyntaxHighlighter
```

(b) Add module-level constants just below `log = logging.getLogger(__name__)` (line 25):

```python
_SYNTAX_SIZE_THRESHOLD = 1024 * 1024  # 1 MiB — above this, highlighting is off
_SYNTAX_DEBOUNCE = 0.25               # seconds to wait after edits before retokenizing
```

(c) In `__init__`, after `self._line_map: list[int] = []` (line 107), add:

```python
        self._highlighter = SyntaxHighlighter()
        self._syntax_spans: list[list[Span]] = []
        self._highlight_enabled = True
        self._syntax_timer = None
```

(d) Replace `on_mount` (lines 136-138) with:

```python
    def on_mount(self) -> None:
        self._rescan_folds()
        self._detect_language()
        self._recompute_syntax()
        self._refresh_render()
```

(e) Add these methods just below `on_mount`:

```python
    def _detect_language(self) -> None:
        sample = "\n".join(self.buffer.lines[:50])
        self._highlighter.detect(self.buffer.file_path, sample)

    def _should_highlight(self) -> bool:
        if not self._highlight_enabled or not self._highlighter.enabled:
            return False
        size = sum(len(line) + 1 for line in self.buffer.lines)
        return size <= _SYNTAX_SIZE_THRESHOLD

    def _recompute_syntax(self) -> None:
        """Retokenize the buffer. Runs in a worker when an app is active;
        falls back to inline computation otherwise (e.g. in unit tests)."""
        if not self._should_highlight():
            if self._syntax_spans:
                self._syntax_spans = []
                self._safe_refresh()
            return
        lines = list(self.buffer.lines)
        try:
            self.run_worker(
                lambda: self._tokenize_worker(lines),
                thread=True, exclusive=True, group="syntax",
            )
        except Exception:
            # No active app — compute synchronously.
            self._apply_syntax_spans(self._highlighter.tokenize(lines))

    def _tokenize_worker(self, lines: list[str]) -> None:
        spans = self._highlighter.tokenize(lines)
        self.call_from_thread(self._apply_syntax_spans, spans)

    def _apply_syntax_spans(self, spans: list[list[Span]]) -> None:
        self._syntax_spans = spans
        self._safe_refresh()

    def _safe_refresh(self) -> None:
        try:
            self.refresh()
        except Exception:
            log.debug("refresh after syntax recompute failed", exc_info=True)

    def _schedule_syntax(self) -> None:
        if self._syntax_timer is not None:
            try:
                self._syntax_timer.stop()
            except Exception:
                pass
        try:
            self._syntax_timer = self.set_timer(_SYNTAX_DEBOUNCE, self._recompute_syntax)
        except Exception:
            # No active app — recompute immediately.
            self._recompute_syntax()
```

(f) In `_post_buffer_update` (lines 451-455), add a scheduling call. Replace the method with:

```python
    def _post_buffer_update(self) -> None:
        self._rescan_folds()
        self._refresh_render()
        self._schedule_syntax()
        self.post_message(self.BufferModified(self, self.buffer.modified))
        self._post_cursor_update()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/windowing/test_editor_highlight.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/editor/widget.py tests/windowing/test_editor_highlight.py
git commit -m "feat(editor): wire syntax highlighter into EditorWidget with debounce"
```

---

## Task 4: render_line compositing refactor (syntax as base layer)

**Files:**
- Modify: `tyui/windowing/editor/widget.py` — replace `render_line` (lines 187-269); remove now-unused `_append_with_search_and_fold` (lines 295-313); add `_syntax_spans_rendered` helper.
- Test: `tests/windowing/test_editor_highlight.py` (append)

This unifies the three render branches into one priority compositor:
`syntax (lowest) < fold placeholder < search match < selection < cursor (highest)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/windowing/test_editor_highlight.py
from rich.segment import Segment


def _line_styles(strip):
    return [(seg.text, seg.style) for seg in strip._segments if seg.text]


async def test_keyword_is_styled_in_render():
    app = _Host("def f():\n", "foo.py")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        strip = editor.render_line(0)
        # Some segment must carry a non-default foreground (the keyword colour).
        assert any(
            seg.style is not None and seg.style.color is not None
            for seg in strip._segments if seg.text.strip()
        )


async def test_selection_overrides_syntax():
    app = _Host("def f():\n", "foo.py")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        editor.buffer.start_selection(0, 0)
        editor.buffer.update_selection(0, 3)  # select "def"
        editor.buffer.cursor_row, editor.buffer.cursor_col = 0, 3
        strip = editor.render_line(0)
        # The selection background colour must appear on the selected run.
        sel_bg = editor._rich_style("editor.selection").bgcolor
        assert any(
            seg.style is not None and seg.style.bgcolor == sel_bg
            for seg in strip._segments if seg.text
        )


async def test_render_without_highlight_is_plain():
    app = _Host("def f():\n", "foo.py")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        editor._highlight_enabled = False
        editor._syntax_spans = []
        await pilot.pause()
        strip = editor.render_line(0)
        # No syntax colour on the body when highlighting is off.
        body = [seg for seg in strip._segments if seg.text.strip()
                and not seg.text.strip().isdigit()]
        assert all(seg.style is None or seg.style.color is None for seg in body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_editor_highlight.py -k render -v`
Expected: FAIL on `test_keyword_is_styled_in_render` — current `render_line` does not apply syntax colours.

- [ ] **Step 3: Write minimal implementation**

(a) Add this helper near the other span helpers (e.g. after `_get_search_spans_on_row`, line 293):

```python
    def _syntax_spans_rendered(self, buf_row: int) -> list[tuple[int, int, str]]:
        """Syntax spans for a buffer row, mapped to rendered-column coords."""
        if not self._highlight_enabled:
            return []
        if buf_row < 0 or buf_row >= len(self._syntax_spans):
            return []
        out: list[tuple[int, int, str]] = []
        for s in self._syntax_spans[buf_row]:
            start = self._buffer_col_to_rendered_col(buf_row, s.start)
            end = self._buffer_col_to_rendered_col(buf_row, s.end)
            if end > start:
                out.append((start, end, f"editor.syntax.{s.role}"))
        return out
```

(b) Replace the whole `render_line` method (lines 187-269) with:

```python
    def render_line(self, y: int) -> Strip:
        rendered_idx = y + self.scroll_offset.y
        if rendered_idx >= len(self._rendered_lines):
            return Strip.blank(self.size.width, self.rich_style)

        line = self._rendered_lines[rendered_idx]
        buf_row = self._rendered_row_to_buffer_row(rendered_idx)
        gutter = self._gutter_width()
        base = self.rich_style
        n = len(line)

        # Per-column style array; index n is a slot for a cursor/marker past EOL.
        col_styles: list[RichStyle] = [base] * (n + 1)

        # Layer 0: syntax base.
        for s, e, role in self._syntax_spans_rendered(buf_row):
            style = self._rich_style(role)
            for i in range(max(0, s), min(e, n)):
                col_styles[i] = style

        # Layer 1: fold placeholders.
        fold_style = self._rich_style("editor.fold_marker")
        for s, e in self._get_fold_placeholders_on_row(buf_row):
            for i in range(max(0, s), min(e, n)):
                col_styles[i] = fold_style

        # Layer 2: search matches.
        for s, e, sstyle in self._get_search_spans_on_row(buf_row):
            for i in range(max(0, s), min(e, n)):
                col_styles[i] = sstyle

        # Layer 3: selection.
        sel = self.buffer.selection_range()
        has_sel_on_line = False
        sel_start_vis = sel_end_vis = 0
        er = -1
        if sel:
            (sr, sc), (er, ec) = sel
            if sr <= buf_row <= er:
                has_sel_on_line = True
                if sr == er:
                    sel_start_vis = self._buffer_col_to_rendered_col(buf_row, sc)
                    sel_end_vis = self._buffer_col_to_rendered_col(buf_row, ec)
                else:
                    sel_start_vis = self._buffer_col_to_rendered_col(buf_row, sc) if buf_row == sr else 0
                    sel_end_vis = self._buffer_col_to_rendered_col(buf_row, ec) if buf_row == er else n
        if has_sel_on_line:
            sel_style = self._rich_style("editor.selection")
            for i in range(max(0, sel_start_vis), min(sel_end_vis, n)):
                col_styles[i] = sel_style

        # Layer 4: cursor (only within the line; EOL handled by the marker below).
        vis_col = -1
        if buf_row == self.buffer.cursor_row:
            vis_col = self._buffer_col_to_rendered_col(buf_row, self.buffer.cursor_col)
            in_sel = has_sel_on_line and sel_start_vis <= vis_col < sel_end_vis
            cur_role = "editor.selection_cursor" if in_sel else "editor.cursor"
            if 0 <= vis_col < n:
                col_styles[vis_col] = self._rich_style(cur_role)

        # Trailing marker for a cursor sitting past EOL and/or a selection that
        # continues onto the next line.
        chars = list(line)
        cursor_at_eol = buf_row == self.buffer.cursor_row and vis_col >= n
        sel_spans_newline = has_sel_on_line and buf_row < er
        if cursor_at_eol:
            marker_role = "editor.selection_cursor" if sel_spans_newline else "editor.cursor"
            col_styles[n] = self._rich_style(marker_role)
            chars.append(" ")
        elif sel_spans_newline:
            col_styles[n] = self._rich_style("editor.selection")
            chars.append(" ")

        # Build the Text: gutter, then run-length grouped body.
        text = Text(style=base)
        if self.show_line_numbers:
            line_num = str(buf_row + 1).rjust(gutter - 1)
            text.append(f"{line_num} ", style=self._rich_style("editor.line_numbers"))

        i = 0
        m = len(chars)
        while i < m:
            st = col_styles[i]
            j = i + 1
            while j < m and col_styles[j] == st:
                j += 1
            text.append("".join(chars[i:j]), style=st)
            i = j

        try:
            return Strip(text.render(self.app.console))
        except Exception:
            log.debug("render_line failed for y=%d, returning blank strip", y, exc_info=True)
            return Strip.blank(self.size.width)
```

(c) Delete the now-unused `_append_with_search_and_fold` method (originally lines 295-313).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windowing/test_editor_highlight.py -v`
Expected: PASS (all tests, including the Task 3 ones)

Then run the existing editor render/fold/search tests to confirm no regression:

Run: `pytest tests/windowing/ -k "editor or fold or search" -q`
Expected: PASS (no regressions in selection/search/fold rendering)

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/editor/widget.py tests/windowing/test_editor_highlight.py
git commit -m "refactor(editor): composite render_line layers with syntax base"
```

---

## Task 5: Size-threshold gate test

**Files:**
- Test: `tests/windowing/test_highlight.py` (append) — verifies the threshold logic on `EditorWidget`.

The threshold gate is already implemented in Task 3 (`_should_highlight`). This task locks it with a test.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/windowing/test_highlight.py
def test_should_highlight_threshold(monkeypatch):
    from tyui.windowing.editor import widget as widget_mod
    from tyui.windowing.editor.widget import EditorWidget
    from tyui.windowing.core.buffer import TextBuffer

    buf = TextBuffer.from_string("x = 1\n")
    buf.file_path = "foo.py"
    ed = EditorWidget(buffer=buf)
    ed._highlighter.detect("foo.py", "x = 1\n")
    assert ed._should_highlight() is True

    # Shrink the threshold below the buffer size → highlighting disabled.
    monkeypatch.setattr(widget_mod, "_SYNTAX_SIZE_THRESHOLD", 1)
    assert ed._should_highlight() is False
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/windowing/test_highlight.py::test_should_highlight_threshold -v`
Expected: This should PASS immediately because Task 3 already implemented `_should_highlight` reading the module global. If it FAILS because `_should_highlight` captured the constant by value, change `_should_highlight` to read `widget_mod._SYNTAX_SIZE_THRESHOLD` via the module global (it already references the module-level name `_SYNTAX_SIZE_THRESHOLD`, so monkeypatching the module attribute works).

- [ ] **Step 3: Implementation**

No code change expected (covered by Task 3). If the test failed, ensure `_should_highlight` references the module-level `_SYNTAX_SIZE_THRESHOLD` name directly (not a local copy).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/windowing/test_highlight.py::test_should_highlight_threshold -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/windowing/test_highlight.py
git commit -m "test(editor): cover syntax size-threshold gate"
```

---

## Task 6: Toggle command (Ctrl+H) + set_highlight_enabled

**Files:**
- Modify: `tyui/windowing/editor/widget.py` — add `set_highlight_enabled`.
- Modify: `tyui/windowing/editor/content.py` — add toggle command in `get_commands` (after line 277) and a `_toggle_syntax` handler.
- Test: `tests/windowing/test_editor_highlight.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/windowing/test_editor_highlight.py
from tyui.windowing.editor.content import EditorContent


def test_toggle_command_present():
    content = EditorContent(initial_text="def f():\n", file_path="foo.py")
    ids = {c.id for c in content.get_commands()}
    assert "toggle_syntax" in ids
    cmd = next(c for c in content.get_commands() if c.id == "toggle_syntax")
    assert cmd.hotkey == "ctrl+h"


async def test_toggle_disables_highlight():
    app = _Host("def f():\n", "foo.py")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        assert editor._highlight_enabled is True
        editor.set_highlight_enabled(False)
        await pilot.pause()
        assert editor._highlight_enabled is False
        assert editor._syntax_spans == []
        editor.set_highlight_enabled(True)
        await pilot.pause()
        assert editor._highlight_enabled is True
        assert editor._syntax_spans  # recomputed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_editor_highlight.py -k toggle -v`
Expected: FAIL — `toggle_syntax` command missing / `set_highlight_enabled` undefined.

- [ ] **Step 3: Write minimal implementation**

(a) In `tyui/windowing/editor/widget.py`, add this method (e.g. after `_schedule_syntax`):

```python
    def set_highlight_enabled(self, enabled: bool) -> None:
        self._highlight_enabled = enabled
        if enabled:
            self._recompute_syntax()
        else:
            self._syntax_spans = []
        self._safe_refresh()
```

(b) In `tyui/windowing/editor/content.py`, inside `get_commands` append to the base `commands` list (right before the `if self._enable_folding:` block at line 278) — note the Ctrl+H caveat below:

```python
        commands.append(
            WindowCommand(
                id="toggle_syntax", label="Syntax Highlight",
                handler=self._toggle_syntax, hotkey="ctrl+h",
            ),
        )
        commands.append(
            WindowCommand(
                id="set_language", label="Set Language...",
                handler=self._set_language,
            ),
        )
```

(c) Add the handlers to `EditorContent` (e.g. after `_save_as`, line 305):

```python
    def _toggle_syntax(self) -> None:
        self._editor.set_highlight_enabled(not self._editor._highlight_enabled)

    def _set_language(self) -> None:
        # Delegate to the host app — modal dialogs need Desktop access.
        app = getattr(self, "app", None)
        action = getattr(app, "action_set_language", None)
        if callable(action):
            action(self)
```

> **Ctrl+H caveat (verify during this task):** Many terminals send byte `0x08`
> for both Ctrl+H and Backspace. After implementing, run the manual check in
> Step 4b. If Ctrl+H is delivered as `backspace`, set `hotkey=None` on the
> `toggle_syntax` command (menu-only) and leave a code comment explaining why.
> `_set_language` is added here too so the next task only wires the app side.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windowing/test_editor_highlight.py -k "toggle or command" -v`
Expected: PASS

- [ ] **Step 4b: Manual Ctrl+H verification**

Run: `tyui tyui/app.py` , then press **Ctrl+H** in the editor window.
Expected: highlighting toggles off/on (status/visual change). If instead a
character is deleted (Backspace behavior), apply the caveat fallback above and
re-run Step 4.

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/editor/widget.py tyui/windowing/editor/content.py tests/windowing/test_editor_highlight.py
git commit -m "feat(editor): add syntax-highlight toggle command (Ctrl+H)"
```

---

## Task 7: Manual language picker

**Files:**
- Modify: `tyui/windowing/editor/widget.py` — add `set_language`.
- Modify: `tyui/app.py` — `SetLanguageRequest` dataclass, `action_set_language`, branch in `on_input_dialog_submitted` (line 479-488).
- Test: `tests/windowing/test_editor_highlight.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/windowing/test_editor_highlight.py
async def test_set_language_changes_highlight():
    # Open as a plain extension, then force JSON via the picker API path.
    app = _Host('{"a": 1, "b": "x"}\n', "data.unknownext")
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        await pilot.pause()
        editor.set_language("json")
        await pilot.pause()
        assert editor._highlighter.enabled
        assert editor._syntax_spans
        roles = {s.role for row in editor._syntax_spans for s in row}
        assert roles & {"string", "number", "name"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/windowing/test_editor_highlight.py::test_set_language_changes_highlight -v`
Expected: FAIL — `EditorWidget` has no `set_language`.

- [ ] **Step 3: Write minimal implementation**

(a) In `tyui/windowing/editor/widget.py`, add:

```python
    def set_language(self, name: str | None) -> None:
        self._highlighter.set_language(name)
        self._recompute_syntax()
        self._safe_refresh()
```

(b) In `tyui/app.py`, define the request context next to the other `*Request`
dataclasses (search the file for `class HexSearchRequest` and add nearby):

```python
@dataclass
class SetLanguageRequest:
    editor: object  # the EditorContent whose highlighter to change
```

(Use the same `@dataclass` import already in use for `HexSearchRequest`.)

(c) Add the action method on `TyuiApp` (near `action_save_as`):

```python
    def action_set_language(self, editor) -> None:
        if self.desktop is None:
            return
        self._remember_active_panel_id()
        current = editor._editor._highlighter.language_name
        dialog = InputDialog(
            "Language (Pygments name, e.g. python, json, rust):",
            initial=current,
            context=SetLanguageRequest(editor=editor),
        )
        show_modal(self.desktop, dialog, title="Set Language", size=(60, 5))
        dialog.focus_input()
```

(d) Extend `on_input_dialog_submitted` (line 479) — add a branch before the
final `self._close_modal(event.dialog)`:

```python
        if isinstance(ctx, SetLanguageRequest):
            self._close_modal(event.dialog)
            lang = event.value.strip() or None
            ctx.editor._editor.set_language(lang)
            ctx.editor._editor.focus()
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/windowing/test_editor_highlight.py -v`
Expected: PASS (all editor-highlight tests)

Run: `pytest tests/fm/test_app_skeleton.py -q`
Expected: PASS (app still constructs/imports cleanly with the new dataclass + action)

- [ ] **Step 5: Commit**

```bash
git add tyui/windowing/editor/widget.py tyui/app.py tests/windowing/test_editor_highlight.py
git commit -m "feat(editor): manual language picker via Set Language command"
```

---

## Task 8: Full-suite regression + lint

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS (no regressions; new tests green)

- [ ] **Step 2: Lint**

Run: `ruff check tyui/windowing/core/highlight.py tyui/windowing/editor/widget.py tyui/windowing/editor/content.py tyui/app.py tyui/windowing/themes/modern_dark.py`
Expected: no errors (fix any import-order / unused-import findings inline)

- [ ] **Step 3: Manual smoke**

Run: `tyui tyui/windowing/editor/widget.py`
Expected: the Python file opens with keywords/strings/comments coloured;
selection, F3 search highlight, and fold markers still render correctly over
the colours; Ctrl+H toggles highlighting (or menu command does, per Task 6
caveat); "Set Language..." command changes the lexer.

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A
git commit -m "chore(editor): lint fixes for syntax highlighting"
```

---

## Self-Review notes

- **Spec coverage:** engine=Pygments (T1); per-line cache + debounce (T3); size threshold + worker thread (T3/T5); base ~10 roles (T1 mapping, T2 palette); toggle Ctrl+H (T6); manual language picker (T7); compositing over overlays (T4); tests unit+smoke (T1,T5,T8 / T3,T4,T6,T7). Out-of-scope items (incremental tokenization, detailed palette, viewer highlight, persistence) intentionally omitted.
- **Type consistency:** `Span(start,end,role)` used identically across T1/T3/T4; `_syntax_spans: list[list[Span]]`; `set_language`/`set_highlight_enabled`/`_recompute_syntax`/`_should_highlight`/`_safe_refresh`/`_syntax_spans_rendered` names consistent across tasks. `SetLanguageRequest.editor` is an `EditorContent`; handler reaches the widget via `ctx.editor._editor`.
- **Known risk:** Ctrl+H vs Backspace collision is handled explicitly in T6 with a manual check and fallback.
