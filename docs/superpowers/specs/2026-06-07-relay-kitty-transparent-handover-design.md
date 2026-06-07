# Relay handover: transparent byte bridge + side-channel completion (mc parity)

Date: 2026-06-07
Status: Design — approved for planning
Area: `tyui/fm/console/handover.py`, `tyui/app.py`

## Problem

Running a full-screen TUI (notably `claude`) from tyui's command line works in
`suspend` mode but garbles output in `relay` mode — specifically `Shift+Enter`
produces garbage characters inside the program's render area. The relay mode is
the one we want to keep, because it hosts a **persistent `$SHELL -i`** that
preserves session state (`export`, aliases, activated venv, history) between
commands. `suspend` loses that state on every command.

Goal: **full Midnight Commander parity** — a persistent subshell AND working
full-screen / kitty-keyboard-protocol TUIs, at the same time.

## Root-cause hypothesis (to be confirmed by a spike)

The existing HANDOVER.md blames "nested PTY breaks the kitty keyboard protocol".
That explanation is suspect, because **mc itself runs foreground commands through
an equivalent nested-PTY byte bridge** (`feed_subshell`) and claude works there.
If the PTY layer alone were fatal, mc would break too.

The real difference is **how command completion is detected**:

- **tyui relay** scans the program's stdout stream for a sentinel
  `TYUI_END_<tok>_<rc>` and, in `scan_sentinel`, **holds back the last 64 bytes**
  (`tail`) until more output arrives. Small escape-sequence bursts from claude
  (the kitty support query `CSI ? u` followed by a DA1 `CSI c`, together under
  64 bytes) get **stuck in that holdback buffer and never reach the host
  terminal** (PyCharm) until claude emits ≥64 more bytes — but claude is
  *blocked waiting for the response*. Result: timeout → claude falls back to
  legacy key encoding where `Shift+Enter` collapses to an ambiguous `ESC`+`CR`,
  and its multi-line redraw renders as garbage.
- **mc** sends the completion marker over a **separate channel** (its
  `subshell_pipe`), so the visible stdout is forwarded **byte-for-byte with no
  scanning and no holdback** — the kitty handshake passes cleanly.
- **tyui suspend (works)** has neither scanning nor holdback. This isolates the
  scanning/holdback as the likely culprit — not the PTY layer itself.

## Solution: move completion detection to a side channel; make the bridge transparent

Mirror mc's architecture. Keep the persistent `$SHELL -i` PTY. Stop multiplexing
the completion marker into the visible stdout stream; carry it on a dedicated
FIFO. The terminal byte bridge then forwards verbatim, so escape-sequence
handshakes (kitty, DA1, bracketed paste, etc.) round-trip unmodified.

### Component 1 — Spike to confirm the hypothesis (throwaway)

Before the real rework, run a minimal experiment to validate the root cause:

- Temporarily modify `_pump` to forward each `chunk` to stdout **verbatim**
  (no holdback), while still scanning a *copy* of the accumulated buffer for the
  sentinel to detect completion.
- Launch `claude` in relay mode and test `Shift+Enter`.

Outcome gate:
- **Garbage gone / kitty negotiated** → hypothesis confirmed; proceed to the
  full implementation (Components 2–4).
- **Still broken** → pivot the plan to diagnose termios / shell-startup
  interference instead. (Capture findings; do not proceed with the FIFO rework
  blindly.)

The spike code is discarded; production uses the clean implementation below.

### Component 2 — Side-channel completion signal (FIFO)

- On `_ensure_shell`, create a FIFO at `$TMPDIR/tyui-<uuid>.fifo`
  (`os.mkfifo`, mode 0600).
- Pass the FIFO path to the subshell via an env var (e.g. `TYUI_DONE_FIFO`).
- The prompt hook (`_prompt_hook_setup`) is rewritten so that instead of
  `printf "...TYUI_END..." ` to stdout, it appends the marker to the FIFO:
  `printf '%d\n' "$?" >> "$TYUI_DONE_FIFO"`. (zsh `precmd_functions`, bash
  `PROMPT_COMMAND` prepend, POSIX `PS1` fallback — same shells as today, same
  `$?`-preservation care for bash.)
- tyui opens the FIFO read-end **non-blocking** (`os.open(path,
  O_RDONLY | O_NONBLOCK)`) to avoid the open-blocks-until-writer rendezvous, and
  reads `rc` lines from it.
- `_drain_to_marker` (startup sync) switches to reading the first completion
  from the FIFO rather than scanning stdout.

**Why FIFO, not an inherited fd:** `ptyprocess.PtyProcess.spawn` does not expose
a way to pass arbitrary inherited fds to the child. A FIFO needs no change to the
spawn mechanism — the shell writes to a path from env. Migrating to a raw
`pty.fork()` to gain an inherited fd is heavier and is held in reserve only if
the FIFO approach hits an unforeseen wall.

### Component 3 — Transparent byte bridge

- Rewrite `_pump`: forward `master_fd → sys.stdout.buffer` and
  `stdin → master_fd` **verbatim**, with no `scan_sentinel` and no 64-byte
  holdback.
- Completion is detected by readable bytes on the FIFO read-end, added to the
  `select` watch set alongside `master_fd` and the input fds. Parse `rc` from the
  FIFO line; that ends the pump.
- `_interactive_relay` (the Ctrl+O command screen) moves to the same scheme:
  markers arrive on the FIFO and are never written to the visible screen, so the
  screen stays clean without stdout scanning.
- `scan_sentinel` / `_END_RE` are removed (or retained only if a fallback path
  still needs them; default is removal once the FIFO path is proven).

### Component 4 — cwd synchronisation (mc-style)

Today relay **ignores** the `cwd` argument after the first spawn — commands always
run in the shell's startup directory while `cd` is intercepted by the file
manager (`_handover_cd` moves the panel only). This makes the "persistent
session" half-broken.

- Before sending each command, `run_foreground` issues a quiet
  `cd <panel_cwd>` to the subshell (no echo; its completion marker also goes via
  the FIFO so it doesn't pollute the screen, or it is folded into the same
  command line as `cd <dir> && <cmd>`).
- Optionally, a typed `cd` on the command line is forwarded to the subshell in
  addition to moving the panel, so panel and subshell stay in lockstep (mc
  behaviour). Keep the existing panel-move as the source of truth for the panel.

## Data flow (after)

```
claude  ──stdout──▶ PTY slave ──▶ PTY master ──(verbatim)──▶ real terminal (PyCharm)
claude  ◀──stdin── PTY slave ◀── PTY master ◀──(verbatim)── real terminal stdin
$SHELL precmd ──rc──▶ FIFO ──▶ tyui (select) ──▶ end pump, return rc
```

No program bytes are ever scanned or held back; the completion signal travels
out of band.

## Testing

- **Unit (side channel):** spawn shell, run a command, assert `rc` is read from
  the FIFO and that the marker text never appears in the forwarded stdout
  stream. Multi-line and trailing output is delivered without loss or delay.
- **Bridge fidelity:** bytes (including escape sequences) pass 1:1 in both
  directions; no 64-byte tail latency.
- **cwd sync:** a command run with the active panel at dir X observes cwd == X.
- **Graceful degradation:** non-POSIX / no tty / FIFO creation failure → fall
  back to `SubprocessHandover` (suspend) exactly as today.
- Existing handover tests updated for the new completion mechanism.

## Risks & rollback

- FIFO open semantics — mitigated by `O_RDONLY | O_NONBLOCK` on the read-end and
  reading on the `select` loop.
- Spike may refute the hypothesis → plan pivots to termios/shell-startup
  diagnosis before any rework (gated, no blind build).
- Rollback is cheap: the handover layer is isolated and `suspend` mode remains an
  untouched, working fallback.

## Out of scope

- Windows support (relay is POSIX-only; suspend remains the Windows path).
- Rewriting the thin embedded ANSI console (`backends/`, `window.py`) — this work
  is entirely in the handover layer + its call sites in `app.py`.
