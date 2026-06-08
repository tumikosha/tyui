# User Menu (F2) — Design

Status: approved (brainstorm 2026-06-08)

## 1. Purpose & trigger

A user-configurable menu of frequently-used shell commands, in the spirit of
the **F2 User Menu** in Midnight Commander / Far Manager.

- Opened with **F2**, in both the **file panel** and the **editor**. (F2 was
  freed by moving Project View to F1 in the preceding change.)
- Selecting an entry runs its shell command body through the existing
  **handover** (full TTY, mc-style) with `cwd` = the active panel's directory
  (in the editor: the directory of the file being edited).
- The menu is defined in a **Markdown** file so it is human-readable, easy to
  edit, and naturally supports long / multi-line command bodies.

## 2. File format (Markdown)

```markdown
# User Menu

## Build & Test

### (b) Build project
```bash
make build
```

### (t) Run tests
```bash
pytest -q %d
```

## Git

### (s) Status
```bash
git -C %d status
```
```

Parsing rules:

- `#` (level-1 heading) — file title; ignored.
- `##` (level-2 heading) — a **section header**: a non-selectable group label.
- `###` (level-3 heading) — a **menu entry**. Its text is the entry title.
- **Hotkey**: an optional single character in parentheses at the start of the
  entry title, e.g. `### (b) Build project` → hotkey `b`, title `Build
  project`. Entries without `(x)` have no quick hotkey (reachable by arrows).
- **Body**: the first fenced code block (```` ``` ````) under an entry. May be
  **multi-line**. The code-fence language tag (e.g. ```` ```bash ````) is
  decorative and ignored at execution — the body is fed to `$SHELL`.
- Text that is neither a heading nor a code block (prose between entries) is
  ignored, so authors can annotate freely.

Malformed / unparseable content degrades gracefully: an entry with no code
block is skipped (not shown); a missing or unreadable file yields an empty
list (see §5 for the empty-state flow). Parsing never raises into the UI.

## 3. Location & merge

Both files are loaded and **merged** every time F2 is pressed (the source set
is recomputed, so edits and `cd` are picked up live):

1. **Local**: `./.tyui.menu.md` in the active panel's directory.
2. **Global**: `~/.config/tyui/menu.md` (honours `$XDG_CONFIG_HOME`, like
   `user_config`).

Display order: local entries first, then a separator, then global entries.
Each entry remembers its `source` (local/global) for the F4-edit action.

Hotkey collisions: if a quick hotkey appears in both, the **local** entry wins
for instant-key activation; both remain reachable via arrows.

## 4. Macros (extended set)

Substituted in the body immediately before execution. All path substitutions
are `shlex`-quoted so spaces are safe.

| Macro        | Expands to                                             |
|--------------|--------------------------------------------------------|
| `%f`         | current file (name under the cursor)                   |
| `%d`         | current directory (active panel cwd)                   |
| `%t`         | tagged/selected files, space-joined                    |
| `%s`         | tagged files if any, else the current file             |
| `%F`         | current file of the **other** panel                    |
| `%D`         | directory of the **other** panel                       |
| `%x`         | extension of the current file (without the dot)        |
| `%b`         | basename of the current file without extension         |
| `%%`         | a literal `%`                                          |
| `%{Prompt}`  | ask the user (modal `InputDialog` titled `Prompt`)     |

`%{...}` interactive macros: before running, the body is scanned for all
`%{...}` occurrences; each distinct prompt text is asked once (sequential
`InputDialog`s) and the entered value is substituted (quoted). Cancelling any
prompt aborts the run.

Context resolution is **pure** (no I/O): given the current entry, cursor file,
tagged files, both panels' cwds → a substitution map. Macros referring to
absent context (e.g. `%t` with nothing tagged) expand to empty.

## 5. Dialog UX (flat list with section headers)

- A modal selection list, following the existing `tyui/fm/dialogs.py` pattern,
  wrapped in `ModalWindow` (freeze/thaw of sibling focus is built in — see
  project memory `feedback_modal_dialogs`).
- Rows: section headers render as dim, non-selectable separators; entries
  render as `(b) Build project`-style rows. Cursor skips headers.
- Navigation: **↑/↓** (and `j`/`k`) move; **Enter** runs the highlighted
  entry; pressing an entry's **hotkey character** runs it instantly (mc-style);
  **Esc** cancels.
- **F4 — Edit**: opens the menu file for the highlighted entry's `source`
  (local or global) in tyui's own editor. With no entries, F4 edits the global
  file path.
- **Empty state** (neither file exists): F2 **seeds** `~/.config/tyui/menu.md`
  with a starter example (see §6) and immediately opens it in the editor,
  instead of showing an empty dialog.

## 6. Seeded example (first run)

Written to `~/.config/tyui/menu.md` on first F2 when no menu file exists:

```markdown
# User Menu

## Python

### (v) Activate venv (.venv)
```bash
source %d/.venv/bin/activate
```

### (t) Run tests
```bash
pytest -q
```

## Build

### (b) Build project
```bash
make build
```

## Git

### (s) Status
```bash
git -C %d status
```
```

Note on `source`: the relay handover reuses a single persistent `$SHELL`, so
`source .venv/bin/activate` run from the menu **persists** into subsequent
commands in that session — the venv-activate example works as expected rather
than evaporating after the command returns. (Under the cross-platform
`SubprocessHandover` fallback, each command is a fresh process, so `source`
would not persist; this is documented as a known backend difference.)

## 7. Decomposition (modules)

- **`tyui/fm/user_menu.py`** — pure logic, no I/O, unit-tested:
  - `parse_menu(text: str) -> list[MenuNode]` → ordered list of `Section` /
    `Entry(hotkey, title, body, lang)`.
  - Two-step macro API (keeps the pure engine free of UI prompting):
    `collect_prompts(body: str) -> list[str]` returns the distinct `%{...}`
    prompt labels in order; `expand_macros(body: str, ctx: MacroContext,
    prompt_values: dict[str, str]) -> str` performs all substitutions
    (`%f`/`%d`/… from `ctx`, `%{label}` from `prompt_values`, `%%` → `%`),
    `shlex`-quoting paths.
  - `MacroContext` dataclass: current file, tagged files, panel cwd, other
    panel file/cwd.
- **Loader** (small, fault-tolerant, `user_config`-style): resolve local +
  global paths, read, parse each, merge with `source` tags and a separator.
  Seeding helper writes the starter file.
- **`UserMenuDialog`** — modal selection widget (extends the existing dialog
  base), emits a `Selected(entry)` / `Cancelled` message and exposes an
  `EditRequested(source_path)` message for F4.
- **`app.py` wiring**:
  - Register a focus-scoped `user_menu` command with hotkey **`f2`** on both
    `FilePanel.get_commands()` and the editor content's `get_commands()`.
  - `action_user_menu`: gather `MacroContext` from the active panel (or editor
    file), build merged menu, handle the empty-state seed, show the dialog.
  - On `Selected`: collect any `%{...}` prompts, expand macros, run via the
    existing handover path (`_run_handover_command`-equivalent), append to
    command history. On `EditRequested`: open the file in the editor.

This keeps the parser and macro engine independently testable and free of
Textual / app dependencies; the dialog and app wiring are thin.

## 8. Testing

- **Parser**: sections, entries, hotkeys `(x)`, multi-line bodies, ignored
  prose, `#` title skipped, entry-without-codeblock skipped, empty/garbage
  input → `[]`.
- **Macros**: every `%`-code; path quoting with spaces; `%%` literal;
  `%{prompt}` collection; absent context → empty expansion; basename/ext edge
  cases (no extension, dotfiles).
- **Merge**: local-before-global ordering, separator presence, hotkey-collision
  precedence (local wins).
- **Seeding**: empty state writes the starter file once and not twice.
- **Async smoke** (`run_test`): F2 opens the dialog with merged entries;
  selecting an entry calls the run path with the correct `cwd` (handover
  mocked, as in `tests/fm/console/test_handover.py`); F4 emits an edit request
  for the right source file; F2 with no files seeds + opens the editor.

## 9. Out of scope (YAGNI)

- True nested/navigable submenus (flat sections with headers chosen instead).
- mc menu-file conditional syntax (`=`/`+` pattern guards).
- In-dialog structured add/edit/delete of entries (editing is done by opening
  the Markdown file in the editor).
- Per-entry "pause after run" flags (handover already returns to the UI).
