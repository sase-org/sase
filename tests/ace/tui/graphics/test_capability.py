from __future__ import annotations

import subprocess

import sase.ace.tui.graphics.capability as capability
from sase.ace.tui.graphics import GraphicsCapability, detect_graphics_capability


def _env(**values: str) -> dict[str, str]:
    base = {"TERM": "xterm-kitty", "COLORTERM": "truecolor"}
    base.update(values)
    return base


def _unexpected_probe(passthrough: str, timeout: float) -> bool:
    raise AssertionError("probe should not have been called")


def _mock_tmux_commands(
    monkeypatch,
    outputs: dict[tuple[str, ...], tuple[int, str] | BaseException],
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        assert check is False
        assert capture_output is True
        assert text is True
        assert timeout == capability._TMUX_QUERY_TIMEOUT
        key = tuple(command)
        calls.append(key)
        output = outputs.get(key, (1, ""))
        if isinstance(output, BaseException):
            raise output
        return subprocess.CompletedProcess(
            command,
            output[0],
            stdout=output[1],
            stderr="",
        )

    monkeypatch.setattr(capability.subprocess, "run", fake_run)
    return calls


def _mock_active_probe(
    monkeypatch,
    *,
    select_readable: list[list[int]],
    read_chunks: list[bytes],
) -> tuple[list[bytes], list[tuple[int, int, list[str]]]]:
    writes: list[bytes] = []
    tcsetattrs: list[tuple[int, int, list[str]]] = []

    def fake_fcntl(fd: int, op: int, arg: int | None = None) -> int:
        if op == capability.fcntl.F_GETFL:
            return 0
        return 0

    def fake_select(
        read_fds: list[int],
        write_fds: list[int],
        error_fds: list[int],
        timeout: float,
    ) -> tuple[list[int], list[int], list[int]]:
        readable = select_readable.pop(0) if select_readable else []
        return readable, [], []

    def fake_read(fd: int, size: int) -> bytes:
        return read_chunks.pop(0) if read_chunks else b""

    def fake_write(fd: int, data: bytes) -> int:
        writes.append(data)
        return len(data)

    def fake_tcsetattr(fd: int, action: int, attrs: list[str]) -> None:
        tcsetattrs.append((fd, action, attrs))

    monkeypatch.setattr(capability.os, "isatty", lambda fd: True)
    monkeypatch.setattr(capability.os, "read", fake_read)
    monkeypatch.setattr(capability.os, "write", fake_write)
    monkeypatch.setattr(capability.select, "select", fake_select)
    monkeypatch.setattr(capability.termios, "tcgetattr", lambda fd: ["old"])
    monkeypatch.setattr(capability.termios, "tcsetattr", fake_tcsetattr)
    monkeypatch.setattr(capability.fcntl, "fcntl", fake_fcntl)
    monkeypatch.setattr(capability.tty, "setcbreak", lambda fd: None)

    return writes, tcsetattrs


def test_disabled_env_wins() -> None:
    cap = detect_graphics_capability(
        _env(SASE_TUI_GRAPHICS="off"),
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert "disabled" in cap.reason


def test_unknown_terminal_is_unsupported_without_override() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "COLORTERM": "truecolor"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert cap.probed is False
    assert "not attempted" in cap.reason


def test_known_kitty_is_trusted_without_truecolor() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-kitty"},
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.protocol == "kitty"
    assert cap.terminal == "kitty"
    assert cap.truecolor is False
    assert cap.probed is False


def test_known_kitty_detection_does_not_probe() -> None:
    cap = detect_graphics_capability(
        _env(KITTY_WINDOW_ID="1"),
        probe_func=_unexpected_probe,
    )

    assert cap == GraphicsCapability(
        supported=True,
        protocol="kitty",
        passthrough="none",
        reason="Kitty graphics assumed from terminal environment",
        terminal="kitty",
        truecolor=True,
        probed=False,
    )


def test_known_kitty_without_tmux_records_no_passthrough() -> None:
    cap = detect_graphics_capability(
        _env(KITTY_WINDOW_ID="1"),
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.passthrough == "none"
    assert cap.probed is False


def test_tmux_outer_kitty_with_passthrough_enabled_is_supported(monkeypatch) -> None:
    calls = _mock_tmux_commands(
        monkeypatch,
        {
            ("tmux", "display-message", "-p", "#{client_termname}"): (
                0,
                "xterm-kitty\n",
            ),
            ("tmux", "show", "-gqv", "allow-passthrough"): (0, "all\n"),
        },
    )

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.protocol == "kitty"
    assert cap.passthrough == "tmux"
    assert cap.terminal == "kitty"
    assert cap.probed is False
    assert "Kitty graphics assumed from tmux outer terminal" == cap.reason
    assert calls == [
        ("tmux", "display-message", "-p", "#{client_termname}"),
        ("tmux", "show", "-gqv", "allow-passthrough"),
    ]


def test_tmux_outer_kitty_falls_back_to_show_environment(monkeypatch) -> None:
    calls = _mock_tmux_commands(
        monkeypatch,
        {
            ("tmux", "display-message", "-p", "#{client_termname}"): (1, ""),
            ("tmux", "show-environment", "-g", "TERM"): (
                0,
                "TERM=xterm-kitty\n",
            ),
            ("tmux", "show", "-gqv", "allow-passthrough"): (0, "on\n"),
        },
    )

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.terminal == "kitty"
    assert cap.passthrough == "tmux"
    assert calls == [
        ("tmux", "display-message", "-p", "#{client_termname}"),
        ("tmux", "show-environment", "-g", "TERM"),
        ("tmux", "show", "-gqv", "allow-passthrough"),
    ]


def test_tmux_outer_kitty_without_passthrough_is_unsupported(monkeypatch) -> None:
    _mock_tmux_commands(
        monkeypatch,
        {
            ("tmux", "display-message", "-p", "#{client_termname}"): (
                0,
                "xterm-kitty\n",
            ),
            ("tmux", "show", "-gqv", "allow-passthrough"): (0, "off\n"),
        },
    )

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert cap.passthrough == "tmux"
    assert cap.terminal == "kitty"
    assert "tmux passthrough is not enabled" in cap.reason
    assert cap.probed is False


def test_tmux_metadata_command_failures_fall_back_to_unsupported(
    monkeypatch,
) -> None:
    _mock_tmux_commands(
        monkeypatch,
        {
            ("tmux", "display-message", "-p", "#{client_termname}"): (
                subprocess.TimeoutExpired("tmux", 0.01)
            ),
            ("tmux", "show-environment", "-g", "TERM"): (1, ""),
            ("tmux", "show", "-gqv", "allow-passthrough"): (1, ""),
        },
    )

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert cap.passthrough == "tmux"
    assert cap.terminal is None
    assert cap.truecolor is False
    assert cap.probed is False
    assert "not attempted by default" in cap.reason


def test_unknown_tmux_terminal_is_unsupported_without_override(monkeypatch) -> None:
    _mock_tmux_commands(
        monkeypatch,
        {
            ("tmux", "display-message", "-p", "#{client_termname}"): (
                0,
                "screen-256color\n",
            ),
            ("tmux", "show", "-gqv", "allow-passthrough"): (0, "all\n"),
        },
    )

    cap = detect_graphics_capability(
        {"TERM": "tmux-256color", "TERM_PROGRAM": "tmux", "TMUX": "/tmp/tmux"},
        probe_func=_unexpected_probe,
    )

    assert not cap.supported
    assert cap.passthrough == "tmux"
    assert cap.terminal is None
    assert cap.truecolor is False
    assert cap.probed is False
    assert "not attempted by default" in cap.reason


def test_forced_unknown_tmux_terminal_reports_probe_failure() -> None:
    cap = detect_graphics_capability(
        {
            "TERM": "tmux-256color",
            "TERM_PROGRAM": "tmux",
            "TMUX": "/tmp/tmux",
            "SASE_TUI_GRAPHICS": "kitty",
        },
        probe_func=lambda passthrough, timeout: False,
    )

    assert not cap.supported
    assert cap.passthrough == "tmux"
    assert cap.terminal is None
    assert cap.truecolor is False
    assert cap.probed
    assert "probe did not receive" in cap.reason


def test_forced_tmux_probe_success_enables_kitty_without_truecolor() -> None:
    cap = detect_graphics_capability(
        {
            "TERM": "xterm-256color",
            "TMUX": "/tmp/tmux",
            "SASE_TUI_GRAPHICS": "kitty",
        },
        probe_func=lambda passthrough, timeout: True,
    )

    assert cap.supported
    assert cap.passthrough == "tmux"
    assert cap.truecolor is False


def test_force_kitty_probes_unknown_terminal_without_truecolor() -> None:
    seen: list[str] = []

    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "SASE_TUI_GRAPHICS": "kitty"},
        probe_func=lambda passthrough, timeout: (
            seen.append(passthrough) is None or True
        ),
    )

    assert cap.supported
    assert cap.passthrough == "none"
    assert cap.terminal == "kitty"
    assert cap.truecolor is False
    assert seen == ["none"]


def test_known_ghostty_detection_does_not_probe() -> None:
    cap = detect_graphics_capability(
        _env(TERM="xterm-256color", TERM_PROGRAM="ghostty"),
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.probed is False
    assert cap.terminal == "ghostty"


def test_ghostty_term_detection_does_not_probe() -> None:
    cap = detect_graphics_capability(
        _env(TERM="xterm-ghostty"),
        probe_func=_unexpected_probe,
    )

    assert cap.supported
    assert cap.probed is False
    assert cap.terminal == "ghostty"


def test_probe_can_be_skipped_for_noninteractive_tests() -> None:
    cap = detect_graphics_capability(_env(KITTY_WINDOW_ID="1"), probe=False)

    assert cap.supported
    assert not cap.probed


def test_forced_probe_can_be_skipped_for_noninteractive_tests() -> None:
    cap = detect_graphics_capability(
        {"TERM": "xterm-256color", "SASE_TUI_GRAPHICS": "kitty"},
        probe=False,
    )

    assert cap.supported
    assert cap.terminal == "kitty"
    assert not cap.probed


def test_default_detection_does_not_emit_probe_bytes_or_consume_late_reply(
    monkeypatch,
) -> None:
    delayed_reply = b"\x1b_Gi=31337;OK\x1b\\"
    reads = [delayed_reply]
    writes, tcsetattrs = _mock_active_probe(
        monkeypatch,
        select_readable=[[0]],
        read_chunks=reads,
    )

    cap = detect_graphics_capability(_env(KITTY_WINDOW_ID="1"))

    assert cap.supported
    assert cap.probed is False
    assert writes == []
    assert reads == [delayed_reply]
    assert tcsetattrs == []


def test_active_probe_reports_kitty_support_and_discards_late_reply(
    monkeypatch,
) -> None:
    late_read = b"i=31337;OK"
    reads = [b"\x1b_Gi=31337;OK\x1b\\", late_read]
    writes, tcsetattrs = _mock_active_probe(
        monkeypatch,
        select_readable=[[0], [0], []],
        read_chunks=reads,
    )

    assert capability._probe_kitty_graphics("none", timeout=0.5)
    assert reads == []
    assert b"\x1b[c" not in writes[0]
    assert tcsetattrs == [(0, capability.termios.TCSAFLUSH, ["old"])]


def test_active_probe_flushes_stdin_on_probe_timeout(monkeypatch) -> None:
    writes, tcsetattrs = _mock_active_probe(
        monkeypatch,
        select_readable=[[], []],
        read_chunks=[],
    )

    assert not capability._probe_kitty_graphics("none", timeout=0.5)
    assert writes
    assert tcsetattrs == [(0, capability.termios.TCSAFLUSH, ["old"])]
