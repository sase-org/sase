"""Tests for ``sase tui --tmux`` relaunch argv and profiling env vars."""

from __future__ import annotations

import shlex
import sys
from unittest.mock import patch

import pytest

from sase.main import ace_tmux
from tests.main.ace_tmux_helpers import (
    FakeTmux,
    launch_args,
    patch_screenshot_request_dir,
)


@pytest.fixture(autouse=True)
def _sandbox_screenshot_request_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_screenshot_request_dir(monkeypatch, tmp_path)


def test_strips_tmux_flags_from_relaunch_argv(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    argv = [
        "sase",
        "tui",
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
        ace_tmux.launch_ace_in_tmux(launch_args())

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
        "tui",
        "my-query",
        "--tab",
        "agents",
        "--profile",
    ]
    assert "--tmux" not in parsed
    assert "-T" not in parsed


def test_relaunch_replaces_legacy_ace_subcommand(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "ace", "--tmux", "my-query"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [sys.executable, "-m", "sase", "tui", "my-query"]


def test_relaunch_preserves_global_options_before_tui(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(
            sys,
            "argv",
            ["sase", "-p", "-f", "provider_drain", "tui", "--tmux", "my query"],
        ),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "-p",
        "-f",
        "provider_drain",
        "tui",
        "my query",
    ]


def test_relaunch_preserves_separator_query_flags(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(
            sys,
            "argv",
            ["sase", "tui", "--tmux", "ready", "--", "--tmux", "-T"],
        ),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    relaunch_cmd = new_window_call[-1]
    parsed = shlex.split(relaunch_cmd[len("exec ") :])
    assert parsed == [
        sys.executable,
        "-m",
        "sase",
        "tui",
        "ready",
        "--",
        "--tmux",
        "-T",
    ]


def test_sets_profiling_env_vars_by_default(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    # tmux's `-e KEY=VAL` is repeated per env var.
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert "SASE_TUI_TRACE=1" in e_values
    assert "SASE_TUI_PERF=1" in e_values
    assert any(value.startswith("SASE_TUI_SCREENSHOT_DIR=") for value in e_values)


def test_sets_screenshot_env_to_printed_request_dir(capsys, monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    out = capsys.readouterr().out
    screenshot_dir = next(
        line.partition("=")[2]
        for line in out.splitlines()
        if line.startswith("sase_screenshot_dir=")
    )
    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    e_values = [
        new_window_call[i + 1] for i, tok in enumerate(new_window_call) if tok == "-e"
    ]
    assert f"SASE_TUI_SCREENSHOT_DIR={screenshot_dir}" in e_values
    assert screenshot_dir


def test_respects_explicit_profiling_env_var(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
    monkeypatch.setenv("SASE_TUI_TRACE", "0")
    monkeypatch.delenv("SASE_TUI_PERF", raising=False)
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

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
    fake = FakeTmux(in_tmux=True)
    with (
        patch("sase.main.ace_tmux.shutil.which", return_value="/usr/bin/tmux"),
        patch("sase.main.ace_tmux.subprocess.run", side_effect=fake),
        patch.object(sys, "argv", ["sase", "tui"]),
    ):
        ace_tmux.launch_ace_in_tmux(launch_args())

    new_window_call = next(c for c in fake.calls if c[1] == "new-window")
    name_idx = new_window_call.index("-n")
    e_indices = [i for i, tok in enumerate(new_window_call) if tok == "-e"]
    assert e_indices, "expected at least one -e KEY=VAL pair"
    # Every -e must precede -n so it applies to the new window, not the
    # relaunch command's operands.
    assert max(e_indices) < name_idx
