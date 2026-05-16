"""Tests for ``sase ace --tmux`` window launching."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest

from sase.main import ace_tmux


def _completed(
    cmd: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


class _FakeTmux:
    """Stand-in for ``subprocess.run`` that records calls and scripts tmux."""

    def __init__(
        self,
        *,
        in_tmux: bool,
        session_name: str = "agent-session-7",
        existing_windows: tuple[str, ...] = (),
        new_window_pattern: str = "{session}:@{n}",
        pane_pid_base: int = 82316,
    ) -> None:
        self.in_tmux = in_tmux
        self.session_name = session_name
        self.existing_windows = list(existing_windows)
        self.new_window_pattern = new_window_pattern
        self.pane_pid_base = pane_pid_base
        self.pane_pid_counter = 0
        self.calls: list[list[str]] = []

    def __call__(
        self, cmd: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        assert cmd[0] == "tmux"

        sub = cmd[1]
        if sub == "display-message":
            return _completed(cmd, stdout=self.session_name + "\n")
        if sub == "has-session":
            return _completed(cmd, returncode=0 if not self.in_tmux else 1)
        if sub == "list-windows":
            return _completed(cmd, stdout="\n".join(self.existing_windows) + "\n")
        if sub == "new-session":
            return _completed(cmd)
        if sub == "new-window":
            assert "-n" in cmd
            window_name = cmd[cmd.index("-n") + 1]
            if window_name in self.existing_windows:
                return _completed(
                    cmd,
                    returncode=1,
                    stderr=f"duplicate window: {window_name}\n",
                )
            self.existing_windows.append(window_name)
            session = self.session_name if self.in_tmux else ace_tmux._AGENTS_SESSION
            n = len(self.existing_windows)
            target = self.new_window_pattern.format(session=session, n=n)
            self.pane_pid_counter += 1
            pane_pid = self.pane_pid_base + self.pane_pid_counter
            return _completed(cmd, stdout=f"{target} {pane_pid}\n")
        raise AssertionError(f"unexpected tmux subcommand: {cmd}")


def _args() -> argparse.Namespace:
    return argparse.Namespace(tmux=True)


def test_returns_sase_tmux_1_on_fresh_session(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace", "my-query"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_1" in out
    assert "sase_tmux_session=agent-session-7" in out
    assert "sase_tmux_target" not in out
    # The PID reported must be the fake pane pid (first window → base + 1),
    # not the parent process's PID. This locks in that we surface the child.
    assert f"sase_tmux_pid={fake.pane_pid_base + 1}" in out


def test_skips_occupied_window_numbers(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True, existing_windows=("sase_tmux_1",))
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    out = capsys.readouterr().out
    assert "sase_tmux_window=sase_tmux_2" in out
    # We should have tried sase_tmux_1 first and then sase_tmux_2.
    new_window_calls = [c for c in fake.calls if c[1] == "new-window"]
    assert len(new_window_calls) == 2
    assert new_window_calls[0][new_window_calls[0].index("-n") + 1] == "sase_tmux_1"
    assert new_window_calls[1][new_window_calls[1].index("-n") + 1] == "sase_tmux_2"


def test_strips_tmux_flags_from_relaunch_argv(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True)
    argv = [
        "sase",
        "ace",
        "--tmux",
        "-T",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", argv),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    # The relaunch is now a single shell command string at the end of argv,
    # prefixed with 'exec ' so tmux's #{pane_pid} reports the Python PID.
    relaunch_cmd = new_window_call[-1]
    assert relaunch_cmd.startswith("exec ")
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "ace",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    assert "--tmux" not in parsed
    assert "-T" not in parsed


def test_inside_tmux_uses_current_session(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = _FakeTmux(in_tmux=True, session_name="my-session")
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == "my-session:"
    # We should NOT have created or checked for the agents session.
    assert not any(c[1] == "has-session" for c in fake.calls)
    assert not any(c[1] == "new-session" for c in fake.calls)


def test_outside_tmux_creates_agents_session(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    fake = _FakeTmux(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert any(
        c[1] == "has-session" and ace_tmux._AGENTS_SESSION in c for c in fake.calls
    )
    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    target_arg = new_window_call[new_window_call.index("-t") + 1]
    assert target_arg == f"{ace_tmux._AGENTS_SESSION}:"


def test_outside_tmux_creates_session_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)

    class _FakeNoSession(_FakeTmux):
        def __call__(
            self, cmd: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            self.calls.append(list(cmd))
            if cmd[1] == "has-session":
                return _completed(cmd, returncode=1, stderr="no such session\n")
            return super().__call__(cmd, **kwargs)

    fake = _FakeNoSession(in_tmux=False)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert any(c[1] == "new-session" for c in fake.calls)


def test_sets_profiling_env_vars_by_default(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    # tmux's `-e KEY=VAL` is repeated per env var.
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert "SASE_TUI_TRACE=1" in e_values
    assert "SASE_TUI_PERF=1" in e_values


def test_respects_explicit_profiling_env_var(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.setenv("SASE_TUI_TRACE", "0")
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert "SASE_TUI_TRACE=0" in e_values
    assert "SASE_TUI_PERF=1" in e_values


def test_profiling_env_args_precede_window_name(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = _FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace"]),
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    name_idx = new_window_call.index("-n")
    e_indices = [i for i, tok in enumerate(new_window_call) if tok == "-e"]
    assert e_indices, "expected at least one -e KEY=VAL pair"
    # Every -e must precede -n so it applies to the new window, not the
    # relaunch command's operands.
    assert max(e_indices) < name_idx


def test_exits_with_message_when_tmux_missing(capsys) -> None:
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value=None),
        pytest.raises(SystemExit) as excinfo,
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "tmux executable not found" in err
