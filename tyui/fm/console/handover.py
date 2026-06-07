"""Terminal handover: give the real terminal to a foreground program
(mc-style) and come back. Two strategies behind one protocol.

- RelayHandover (POSIX): one long-lived $SHELL in a PTY; during a command we
  byte-bridge the real terminal to that PTY raw (no emulation). Command end is
  detected via an echoed sentinel ``TYUI_END_<tok>_<rc>`` (shell-agnostic).
- SubprocessHandover (cross-platform): subprocess.run on the inherited tty.

Both run inside ``with app.suspend(): ...`` so Textual leaves its alt-screen,
restores the terminal, then redraws the whole UI on exit.
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

# Matches the EXPANDED sentinel only: token is alphanumeric, rc is an
# optional-minus integer. The echoed input line `...TYUI_END_t_$?` never
# matches because `$?` is not digits.
_END_RE = re.compile(rb"TYUI_END_([0-9a-zA-Z]+)_(-?[0-9]+)\r?\n")


def _term_size() -> tuple[int, int]:
    """(cols, rows) of the real terminal, with a sane fallback."""
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 80, 24


def _prompt_hook_setup(shell_name: str, token: str) -> str:
    """A shell command that makes the shell print ``TYUI_END_<token>_<rc>``
    right before each prompt.

    The marker is emitted by the SHELL when it returns to its prompt — it is
    NOT fed into the shell's input. That distinction is the whole point: an
    interactive child (htop, vim, less) reads stdin, so any sentinel queued in
    the input buffer ahead of it would be consumed as keystrokes. A prompt
    hook fires only after the child exits, so the child's input stays clean.
    """
    mark = f"TYUI_END_{token}_"
    if shell_name == "zsh":
        # Additive via precmd_functions so the user's own precmd hooks survive.
        return (
            f'__tyui_precmd() {{ printf "\\n{mark}%d\\n" "$?" }}; '
            f"precmd_functions+=(__tyui_precmd)\n"
        )
    if shell_name == "bash":
        # Prepend so we read $? before any pre-existing PROMPT_COMMAND mutates
        # it; restore $? afterwards for chained commands.
        return (
            f"__tyui_mark() {{ local s=$?; printf '\\n{mark}%d\\n' \"$s\"; "
            f"return $s; }}; "
            f'PROMPT_COMMAND="__tyui_mark${{PROMPT_COMMAND:+;$PROMPT_COMMAND}}"\n'
        )
    # Unknown / POSIX sh: best-effort. Embed real newlines and rely on $?
    # expansion in PS1 at prompt time. (Replaces the user's prompt.)
    return f"PS1='\n{mark}$?\n'\n"


def scan_sentinel(
    buf: bytearray, tail: int = 64
) -> tuple[bytes, int | None, bytearray]:
    """Scan ``buf`` for a completion sentinel.

    Returns ``(emit, rc, remaining)``:
    - no sentinel yet -> ``rc is None``; emit everything except the last
      ``tail`` bytes (held back so a marker split across reads is not missed),
      ``remaining`` is the held-back tail.
    - sentinel found -> ``rc`` is the parsed exit code; ``emit`` is the bytes
      before the marker; ``remaining`` is the bytes after it. The marker bytes
      themselves are dropped (never forwarded to the terminal).
    """
    m = _END_RE.search(buf)
    if m is None:
        if len(buf) <= tail:
            # Return a fresh bytearray (not buf itself) so callers can safely
            # append with += without mutating the original buffer.
            return b"", None, bytearray(buf)
        return bytes(buf[:-tail]), None, bytearray(buf[-tail:])
    # TODO: validate m.group(1) (the token) against a caller-supplied token to
    # prevent false-positive sentinel matches from unrelated subprocess output.
    rc = int(m.group(2))
    return bytes(buf[: m.start()]), rc, bytearray(buf[m.end() :])


@runtime_checkable
class TerminalHandover(Protocol):
    def run_foreground(self, cmd: str, cwd: Path) -> int: ...
    def command_screen(self, cwd: Path) -> None: ...
    def shutdown(self) -> None: ...


# Ctrl+O byte: toggles in/out of the interactive command screen.
_TOGGLE = 0x0F


class SubprocessHandover:
    """Cross-platform handover: a fresh subprocess on the inherited real tty."""

    name = "subprocess"

    def __init__(self, app, *, runner: Callable = subprocess.run) -> None:
        self._app = app
        self._runner = runner
        # Lazily-built relay used ONLY for the command screen, so Ctrl+O toggles
        # in/out exactly like in `we` (relay) mode. Commands still run via
        # subprocess; this relay's shell only backs the interactive screen.
        self._relay: "RelayHandover | None" = None

    def run_foreground(self, cmd: str, cwd: Path) -> int:
        with self._app.suspend():
            result = self._runner(cmd, shell=True, cwd=str(cwd))
            return getattr(result, "returncode", 0) or 0

    def command_screen(self, cwd: Path) -> None:
        # On POSIX with a real tty, reuse the relay's interactive screen so the
        # user toggles back with Ctrl+O (consistent with `we`).
        if sys.platform != "win32" and sys.stdin.isatty():
            if self._relay is None:
                self._relay = RelayHandover(self._app)
            self._relay.command_screen(cwd)
            return
        # Windows / no tty: drop into a plain interactive shell; the user
        # returns with `exit` / Ctrl+D (no way to intercept a toggle key).
        shell = os.environ.get("SHELL") or os.environ.get("COMSPEC", "/bin/sh")
        with self._app.suspend():
            subprocess.run([shell], cwd=str(cwd))

    def shutdown(self) -> None:
        if self._relay is not None:
            self._relay.shutdown()
            self._relay = None


class RelayHandover:
    """POSIX persistent-subshell relay (Midnight-Commander style).

    One ``$SHELL -i`` lives in a PTY. Only ``<cmd>\\n`` is ever written to the
    shell's input; command completion is detected via a prompt hook installed
    once at startup (see :func:`_prompt_hook_setup`), which makes the shell
    print ``TYUI_END_<tok>_<rc>`` when it returns to its prompt. During the
    command the real terminal is bridged raw to the PTY (no emulation).
    """

    name = "relay"

    def __init__(self, app) -> None:
        self._app = app
        self._proc = None  # ptyprocess.PtyProcess | None
        self._token = ""

    def _ensure_shell(self, cwd: Path) -> None:
        if self._proc is not None and self._proc.isalive():
            return
        from ptyprocess import PtyProcess

        shell = os.environ.get("SHELL", "/bin/sh")
        env = dict(os.environ)
        cols, rows = _term_size()
        self._proc = PtyProcess.spawn(
            [shell, "-i"], cwd=str(cwd), env=env, dimensions=(rows, cols)
        )
        self._token = uuid.uuid4().hex[:12]
        setup = _prompt_hook_setup(os.path.basename(shell), self._token)
        self._proc.write(setup.encode("utf-8"))
        # Swallow shell startup + the hook-install echo, up to the first marker,
        # so the next command starts at a clean point.
        self._drain_to_marker()

    def _drain_to_marker(self, timeout: float = 5.0) -> None:
        if self._proc is None:
            return
        buf = bytearray()
        while True:
            try:
                r, _, _ = select.select([self._proc.fd], [], [], timeout)
            except InterruptedError:
                continue
            if not r:
                return  # timed out — proceed best-effort
            try:
                chunk = os.read(self._proc.fd, 4096)
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
            _, rc, buf = scan_sentinel(buf)
            if rc is not None:
                return

    def _send_command(self, cmd: str) -> None:
        """Write ONLY the command line to the shell — never a sentinel (an
        interactive child would otherwise eat queued sentinel bytes)."""
        assert self._proc is not None
        self._proc.write((cmd + "\n").encode("utf-8", errors="replace"))

    def _pump(self, in_fds: list[int], master_fd: int, out) -> int:
        """Bridge bytes until the sentinel. ``in_fds`` -> master (raw keys),
        master -> ``out`` (program output, sentinel stripped). Returns rc."""
        buf = bytearray()
        watch = [master_fd, *in_fds]
        while True:
            try:
                readable, _, _ = select.select(watch, [], [])
            except InterruptedError:
                continue
            for fd in list(in_fds):
                if fd in readable:
                    data = os.read(fd, 4096)
                    if data:
                        os.write(master_fd, data)
                    else:
                        # EOF on this input fd: stop watching it so select
                        # doesn't spin reporting it readable forever.
                        in_fds = [f for f in in_fds if f != fd]
                        watch = [master_fd, *in_fds]
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    return 0
                if not chunk:
                    return 0
                buf.extend(chunk)
                emit, rc, buf = scan_sentinel(buf)
                if emit:
                    out.write(emit)
                    out.flush()
                if rc is not None:
                    return rc

    def run_foreground(self, cmd: str, cwd: Path) -> int:
        self._ensure_shell(cwd)
        import termios
        import tty

        stdin_fd = sys.stdin.fileno()
        old = termios.tcgetattr(stdin_fd)
        with self._app.suspend():
            tty.setraw(stdin_fd)
            try:
                assert self._proc is not None
                self._propagate_winsize()
                self._send_command(cmd)
                return self._pump([stdin_fd], self._proc.fd, sys.stdout.buffer)
            finally:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old)

    def _propagate_winsize(self) -> None:
        if self._proc is None:
            return
        cols, rows = _term_size()
        try:
            self._proc.setwinsize(rows, cols)
        except Exception:
            pass

    def command_screen(self, cwd: Path) -> None:
        """Ctrl+O: drop into the live subshell interactively until the user
        presses Ctrl+O again (mc-style toggle). Completion markers are stripped
        from the view; the user can type commands and watch output."""
        self._ensure_shell(cwd)
        import termios
        import tty

        stdin_fd = sys.stdin.fileno()
        old = termios.tcgetattr(stdin_fd)
        with self._app.suspend():
            tty.setraw(stdin_fd)
            try:
                assert self._proc is not None
                self._propagate_winsize()
                self._proc.write(b"\n")  # nudge a fresh prompt into view
                self._interactive_relay(
                    stdin_fd, self._proc.fd, sys.stdout.buffer
                )
            finally:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old)

    def _interactive_relay(self, stdin_fd: int, master_fd: int, out) -> None:
        """Bridge the real terminal to the subshell until Ctrl+O. Unlike
        :meth:`_pump`, completion markers are stripped but NOT treated as an
        exit — we stay until the user toggles out."""
        buf = bytearray()
        while True:
            try:
                readable, _, _ = select.select(
                    [master_fd, stdin_fd], [], [], 0.05
                )
            except InterruptedError:
                continue
            if not readable:
                # Idle: flush any held-back tail (e.g. the prompt) so it shows.
                if buf:
                    out.write(bytes(buf))
                    out.flush()
                    buf.clear()
                continue
            # Drain the shell BEFORE acting on the toggle so pending output is
            # not lost when leaving.
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    return
                if not chunk:
                    return
                buf.extend(chunk)
                while True:
                    emit, rc, buf = scan_sentinel(buf)
                    if emit:
                        out.write(emit)
                        out.flush()
                    if rc is None:
                        break  # only a (possibly partial) tail remains
            if stdin_fd in readable:
                data = os.read(stdin_fd, 4096)
                if not data:
                    return
                i = data.find(_TOGGLE)
                if i != -1:
                    if i:
                        os.write(master_fd, data[:i])
                    return
                os.write(master_fd, data)

    def shutdown(self) -> None:
        import signal

        if self._proc is not None and self._proc.isalive():
            try:
                self._proc.kill(signal.SIGTERM)
            except Exception:
                pass
        self._proc = None


def make_handover(app, mode: str) -> TerminalHandover:
    """Pick a handover strategy. ``mode`` is "relay" or "suspend"."""
    if mode == "suspend":
        return SubprocessHandover(app)
    if sys.platform == "win32":
        app.notify(
            "relay terminal mode is POSIX-only; using suspend mode",
            severity="warning",
        )
        return SubprocessHandover(app)
    if not sys.stdin.isatty():
        return SubprocessHandover(app)
    return RelayHandover(app)
