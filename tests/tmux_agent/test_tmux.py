"""Tests for the injectable tmux wrapper and version parser."""

from __future__ import annotations

import pytest

from sase.tmux_agent.tmux import (
    TmuxRunner,
    inside_tmux,
    parse_tmux_version,
    tmux_agent_self_command,
    tmux_available,
)

from .fakes import FakeTmuxRunner


def test_parse_tmux_version_tmux_3_5a() -> None:
    assert parse_tmux_version("tmux 3.5a") == (3, 5)


def test_parse_tmux_version_tmux_3_3() -> None:
    assert parse_tmux_version("tmux 3.3") == (3, 3)


def test_parse_tmux_version_bare_major_minor() -> None:
    assert parse_tmux_version("3.4") == (3, 4)


def test_parse_tmux_version_major_only_defaults_minor_to_zero() -> None:
    assert parse_tmux_version("tmux 4") == (4, 0)


def test_parse_tmux_version_unreadable_returns_none() -> None:
    assert parse_tmux_version("not a version") is None


def test_inside_tmux_true_when_tmux_set() -> None:
    assert inside_tmux({"TMUX": "/tmp/tmux-1000/default,1,0"}) is True


def test_inside_tmux_true_when_only_tmux_pane_set() -> None:
    assert inside_tmux({"TMUX_PANE": "%0"}) is True


def test_inside_tmux_false_when_neither_marker_set() -> None:
    assert inside_tmux({}) is False


def test_tmux_available_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.tmux_agent.tmux.shutil.which",
        lambda name: "/usr/bin/tmux" if name == "tmux" else None,
    )
    assert tmux_available() is True
    monkeypatch.setattr("sase.tmux_agent.tmux.shutil.which", lambda _name: None)
    assert tmux_available() is False


def test_self_command_prefers_path_sase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.tmux_agent.tmux.shutil.which",
        lambda name: "/usr/bin/sase" if name == "sase" else None,
    )
    assert tmux_agent_self_command() == "sase tmux-agent"


def test_self_command_falls_back_to_python_m_sase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.tmux_agent.tmux.shutil.which", lambda _name: None)
    monkeypatch.setattr("sase.tmux_agent.tmux.sys.executable", "/opt/venv/bin/python")
    assert tmux_agent_self_command() == "/opt/venv/bin/python -m sase tmux-agent"


def test_list_windows_parses_index_name_pairs() -> None:
    runner = FakeTmuxRunner(windows=((1, "zsh"), (2, "ai"), (4, "ai3")))
    assert runner.list_windows() == ((1, "zsh"), (2, "ai"), (4, "ai3"))
    assert runner.calls_for("list-windows") == [
        ["tmux", "list-windows", "-F", "#{window_index}:#{window_name}"]
    ]


def test_list_windows_skips_malformed_lines() -> None:
    runner = TmuxRunner(
        run=lambda args: __import__("subprocess").CompletedProcess(
            list(args),
            0,
            "0:zsh\nbadline\n2:ai:extra\n\n",
            "",
        )
    )
    assert runner.list_windows() == ((0, "zsh"), (2, "ai:extra"))


def test_current_pane_directory() -> None:
    runner = FakeTmuxRunner(pane_dir="/tmp/pane dir")
    assert runner.current_pane_directory() == "/tmp/pane dir"
    assert runner.calls_for("display-message") == [
        ["tmux", "display-message", "-p", "#{pane_current_path}"]
    ]


def test_tmux_version_parses_runner_output() -> None:
    runner = FakeTmuxRunner(version_output="tmux 3.4")
    assert runner.tmux_version() == (3, 4)


def test_new_window_emits_c_n_e_and_command() -> None:
    runner = FakeTmuxRunner()
    result = runner.new_window(
        name="ai",
        directory="/tmp/project",
        command="clear; claude; tmux wait-for -S ch",
        env=(("EDITOR", "nvim"), ("FOO", "bar")),
    )
    assert result.returncode == 0
    assert runner.calls_for("new-window") == [
        [
            "tmux",
            "new-window",
            "-n",
            "ai",
            "-c",
            "/tmp/project",
            "-e",
            "EDITOR=nvim",
            "-e",
            "FOO=bar",
            "clear; claude; tmux wait-for -S ch",
        ]
    ]


def test_rename_window_targets_index() -> None:
    runner = FakeTmuxRunner()
    runner.rename_window(3, "ai2")
    assert runner.calls_for("rename-window") == [
        ["tmux", "rename-window", "-t", "3", "ai2"]
    ]


def test_run_shell_background_uses_dash_b() -> None:
    runner = FakeTmuxRunner()
    runner.run_shell_background("tmux wait-for ch && sase tmux-agent --renumber")
    assert runner.calls_for("run-shell") == [
        [
            "tmux",
            "run-shell",
            "-b",
            "tmux wait-for ch && sase tmux-agent --renumber",
        ]
    ]
