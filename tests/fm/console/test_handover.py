import io
import os
import sys
from contextlib import contextmanager

import pytest

from tyui.fm.console.handover import SubprocessHandover, scan_sentinel


def test_scan_sentinel_no_marker_holds_back_tail():
    buf = bytearray(b"hello world")  # 11 bytes, < tail
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b""
    assert rc is None
    assert bytes(rest) == b"hello world"


def test_scan_sentinel_emits_all_but_tail_when_long():
    buf = bytearray(b"x" * 100)
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b"x" * 36
    assert rc is None
    assert rest == bytearray(b"x" * 64)


def test_scan_sentinel_finds_marker_and_extracts_rc():
    buf = bytearray(b"output here\nTYUI_END_abc123_0\nleftover")
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b"output here\n"
    assert rc == 0
    assert bytes(rest) == b"leftover"


def test_scan_sentinel_negative_rc():
    buf = bytearray(b"TYUI_END_deadbeef_-1\n")
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b""
    assert rc == -1


def test_scan_sentinel_ignores_unexpanded_echo_line():
    # The echoed command `echo "TYUI_END_t_$?"` must NOT match (the `$?` is
    # not digits), only the real expanded output does.
    buf = bytearray(b'echo "TYUI_END_t_$?"\nTYUI_END_t_0\n')
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert rc == 0
    assert b'echo "TYUI_END_t_$?"' in emit


def test_scan_sentinel_crlf_line_ending():
    # PTYs on POSIX in raw mode produce \r\n; the regex must accept it.
    buf = bytearray(b"output\r\nTYUI_END_tok5_42\r\nleftover")
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b"output\r\n"
    assert rc == 42
    assert bytes(rest) == b"leftover"


def test_scan_sentinel_exact_tail_boundary_holds_all():
    # When len(buf) == tail the entire buffer must be held back (<=, not <).
    buf = bytearray(b"x" * 64)
    emit, rc, rest = scan_sentinel(buf, tail=64)
    assert emit == b""
    assert rc is None
    assert rest == bytearray(b"x" * 64)


class _FakeApp:
    """Stand-in for TyuiApp: suspend() is a no-op context manager."""

    def __init__(self):
        self.notes = []

    @contextmanager
    def suspend(self):
        yield

    def notify(self, msg, severity="information"):
        self.notes.append((severity, msg))


class _FakeCompleted:
    def __init__(self, rc):
        self.returncode = rc


def test_subprocess_handover_runs_in_suspend_and_returns_rc(tmp_path):
    calls = {}

    def fake_runner(cmd, shell, cwd):
        calls["cmd"] = cmd
        calls["shell"] = shell
        calls["cwd"] = cwd
        return _FakeCompleted(7)

    h = SubprocessHandover(_FakeApp(), runner=fake_runner)
    rc = h.run_foreground("htop", tmp_path)

    assert rc == 7
    assert calls == {"cmd": "htop", "shell": True, "cwd": str(tmp_path)}


from tyui.fm.console.handover import RelayHandover, make_handover


def test_make_handover_suspend_mode_picks_subprocess():
    h = make_handover(_FakeApp(), "suspend")
    assert isinstance(h, SubprocessHandover)


def test_make_handover_windows_degrades_to_subprocess(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    app = _FakeApp()
    h = make_handover(app, "relay")
    assert isinstance(h, SubprocessHandover)
    assert app.notes  # a degradation warning was emitted


def test_make_handover_no_tty_degrades_to_subprocess(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    h = make_handover(_FakeApp(), "relay")
    assert isinstance(h, SubprocessHandover)


def test_make_handover_posix_tty_picks_relay(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    h = make_handover(_FakeApp(), "relay")
    assert isinstance(h, RelayHandover)


def test_relay_pump_emits_output_and_stops_at_sentinel():
    h = RelayHandover(_FakeApp())
    master, slave = os.openpty()
    try:
        os.write(slave, b"hello\nTYUI_END_deadbeef_0\nignored-after")
        out = io.BytesIO()
        # No input fds -> pump only forwards master->out until the sentinel.
        rc = h._pump([], master, out)
        assert rc == 0
        assert b"hello" in out.getvalue()
        assert b"ignored-after" not in out.getvalue()
    finally:
        os.close(master)
        os.close(slave)


def test_relay_sends_only_command_no_sentinel():
    # Regression: the per-command PTY write must carry ONLY the command — never
    # an appended sentinel. (The old code wrote `cmd\necho "TYUI_END..."\n`,
    # which an interactive child like htop consumed as keystrokes.)
    h = RelayHandover(_FakeApp())

    class _CapturingProc:
        def write(self, data):
            self.last = data

    h._proc = _CapturingProc()
    h._send_command("htop")
    assert h._proc.last == b"htop\n"
    assert b"TYUI_END" not in h._proc.last
    assert b"echo" not in h._proc.last


def test_prompt_hook_setup_emits_matchable_marker():
    # The marker the hook prints must be recognised by _END_RE, for each shell.
    from tyui.fm.console.handover import _END_RE, _prompt_hook_setup

    for shell in ("zsh", "bash", "sh", "fish-unknown"):
        setup = _prompt_hook_setup(shell, "deadbeef0000")
        assert "TYUI_END_deadbeef0000_" in setup
        # Simulate what the hook prints at a prompt with rc=0.
        printed = b"\nTYUI_END_deadbeef0000_0\n"
        assert _END_RE.search(printed) is not None


def test_subprocess_command_screen_delegates_to_relay_on_posix_tty(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    calls = []
    monkeypatch.setattr(
        RelayHandover, "command_screen", lambda self, cwd: calls.append(cwd)
    )
    h = SubprocessHandover(_FakeApp())
    h.command_screen(tmp_path)
    assert calls == [tmp_path]
    assert h._relay is not None


def test_subprocess_command_screen_falls_back_without_tty(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    ran = []
    monkeypatch.setattr(
        "tyui.fm.console.handover.subprocess.run",
        lambda *a, **k: ran.append((a, k)),
    )
    h = SubprocessHandover(_FakeApp())
    h.command_screen(tmp_path)
    assert ran  # fell back to launching a plain interactive shell
    assert h._relay is None


def test_subprocess_shutdown_closes_command_screen_relay(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(RelayHandover, "command_screen", lambda self, cwd: None)
    shut = []
    monkeypatch.setattr(RelayHandover, "shutdown", lambda self: shut.append(True))
    h = SubprocessHandover(_FakeApp())
    h.command_screen(tmp_path)
    h.shutdown()
    assert shut == [True]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")
def test_relay_runs_real_command(tmp_path):
    import signal

    def _alarm(_signum, _frame):
        raise TimeoutError("relay pump hung (prompt hook never fired)")

    h = RelayHandover(_FakeApp())
    h._ensure_shell(tmp_path)  # installs the prompt hook + drains startup
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(10)
    try:
        out = io.BytesIO()
        # ONLY the command — completion is detected via the installed prompt
        # hook, not a fed-in sentinel.
        h._send_command("echo marker-hi")
        rc = h._pump([], h._proc.fd, out)
        assert rc == 0
        assert b"marker-hi" in out.getvalue()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
        h.shutdown()


def test_interactive_relay_exits_on_toggle_and_forwards_prefix():
    # Ctrl+O (0x0f) leaves the command screen; bytes before it reach the shell.
    import tty

    h = RelayHandover(_FakeApp())
    master, slave = os.openpty()
    tty.setraw(slave)  # so "ab" (no newline) is readable without canonical wait
    stdin_r, stdin_w = os.pipe()
    try:
        os.write(stdin_w, b"ab\x0fcd")  # "ab" -> shell, then toggle -> exit
        h._interactive_relay(stdin_r, master, io.BytesIO())
        # "ab" was forwarded to the master (readable from the slave side).
        import select as _sel

        r, _, _ = _sel.select([slave], [], [], 1.0)
        assert slave in r
        assert os.read(slave, 64) == b"ab"
    finally:
        os.close(master)
        os.close(slave)
        os.close(stdin_r)
        os.close(stdin_w)


def test_interactive_relay_strips_markers_does_not_exit_on_them():
    # A completion marker in the shell output is stripped from the view and is
    # NOT treated as an exit (we leave only on the toggle / stdin EOF).
    h = RelayHandover(_FakeApp())
    master, slave = os.openpty()
    stdin_r, stdin_w = os.pipe()
    try:
        os.write(slave, b"out\nTYUI_END_deadbeef_0\n")
        os.close(stdin_w)  # stdin EOF -> relay returns (after draining master)
        out = io.BytesIO()
        h._interactive_relay(stdin_r, master, out)
        assert b"out" in out.getvalue()
        assert b"TYUI_END" not in out.getvalue()
    finally:
        os.close(master)
        os.close(slave)
        os.close(stdin_r)


def test_relay_pump_handles_input_fd_eof():
    # An input fd at EOF must not cause a spin; the pump still completes via
    # the master sentinel without hanging.
    h = RelayHandover(_FakeApp())
    r, w = os.pipe()
    os.close(w)  # r is now at EOF (select-readable, read returns b"")
    master, slave = os.openpty()
    try:
        os.write(slave, b"out\nTYUI_END_deadbeef_0\n")
        out = io.BytesIO()
        rc = h._pump([r], master, out)
        assert rc == 0
        assert b"out" in out.getvalue()
    finally:
        os.close(r)
        os.close(master)
        os.close(slave)
