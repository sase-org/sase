"""Tests for ``sase ace --tmux`` window launching."""

from __future__ import annotations

import argparse
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
    ) -> None:
        self.in_tmux = in_tmux
        self.session_name = session_name
        self.existing_windows = list(existing_windows)
        self.new_window_pattern = new_window_pattern
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
            return _completed(cmd, stdout=target + "\n")
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
    assert "sase_tmux_target=agent-session-7:@1" in out
    assert "sase_tmux_pid=" in out


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
    # The relaunch argv lives after '--' in the new-window command.
    sep_idx = new_window_call.index("--")
    relaunch = new_window_call[sep_idx + 1 :]
    assert relaunch == [
        sys.executable,
        "-m",
        "sase",
        "ace",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    assert "--tmux" not in relaunch
    assert "-T" not in relaunch


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


def test_exits_with_message_when_tmux_missing(capsys) -> None:
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value=None),
        pytest.raises(SystemExit) as excinfo,
    ):
        ace_tmux.launch_ace_in_tmux(_args())

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "tmux executable not found" in err
