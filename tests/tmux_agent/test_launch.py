"""Tests for launching an agent CLI in a new tmux window."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.config.tmux_agent import TmuxAgentConfig
from sase.tmux_agent import launch as launch_module
from sase.tmux_agent.launch import (
    TmuxAgentLaunch,
    TmuxAgentLaunchError,
    launch_agent_window,
)

from .fakes import FakeTmuxRunner, make_entry

_CHANNEL = "sase-tmux-agent-testhash12"
_SELF = "sase tmux-agent"


@pytest.fixture(autouse=True)
def _tmux_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch_module, "tmux_available", lambda: True)
    monkeypatch.setattr(launch_module, "inside_tmux", lambda env=None: True)


def _launch(
    tmp_path: Path,
    *,
    runner: FakeTmuxRunner | None = None,
    entry=None,
    config: TmuxAgentConfig | None = None,
    directory: Path | None = None,
    channel: str | None = _CHANNEL,
    self_command: str = _SELF,
):
    target = directory if directory is not None else tmp_path
    return launch_agent_window(
        entry
        or make_entry("claude", argv=("claude", "--dangerously-skip-permissions")),
        directory=str(target),
        config=config or TmuxAgentConfig(),
        runner=runner or FakeTmuxRunner(),
        self_command=self_command,
        channel=channel,
    )


def test_waiter_is_registered_before_new_window(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    result = _launch(tmp_path, runner=runner)

    assert isinstance(result, TmuxAgentLaunch)
    assert result.window_name == "ai"
    assert result.channel == _CHANNEL
    assert result.directory == str(tmp_path)
    assert result.argv == ("claude", "--dangerously-skip-permissions")
    assert [call[1] for call in runner.calls] == [
        "list-windows",
        "run-shell",
        "new-window",
    ]


def test_waiter_invokes_renumber_callback(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    _launch(tmp_path, runner=runner)

    assert runner.calls_for("run-shell") == [
        [
            "tmux",
            "run-shell",
            "-b",
            f"tmux wait-for {_CHANNEL} && {_SELF} --renumber",
        ]
    ]


def test_after_close_command_is_appended_to_waiter(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    _launch(
        tmp_path,
        runner=runner,
        config=TmuxAgentConfig(after_close_command="tm-fix-layout"),
    )

    waiter = runner.calls_for("run-shell")[0][-1]
    assert waiter == (
        f"tmux wait-for {_CHANNEL} && {_SELF} --renumber && tm-fix-layout"
    )


def test_new_window_uses_c_n_e_and_clear_wait_for_shape(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    entry = make_entry(
        "claude",
        argv=("claude", "--dangerously-skip-permissions"),
        env=(("EDITOR", "nvim"),),
    )
    _launch(tmp_path, runner=runner, entry=entry)

    assert runner.calls_for("new-window") == [
        [
            "tmux",
            "new-window",
            "-n",
            "ai",
            "-c",
            str(tmp_path),
            "-e",
            "EDITOR=nvim",
            (
                "clear; claude --dangerously-skip-permissions; "
                f"tmux wait-for -S {_CHANNEL}"
            ),
        ]
    ]


def test_clear_screen_false_omits_clear_prefix(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    _launch(tmp_path, runner=runner, config=TmuxAgentConfig(clear_screen=False))

    command = runner.calls_for("new-window")[0][-1]
    assert (
        command == f"claude --dangerously-skip-permissions; tmux wait-for -S {_CHANNEL}"
    )
    assert not command.startswith("clear;")


def test_directory_with_space_and_quote_is_passed_raw_to_dash_c(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "foo's bar"
    directory.mkdir()
    runner = FakeTmuxRunner()
    result = _launch(tmp_path, runner=runner, directory=directory)

    assert isinstance(result, TmuxAgentLaunch)
    new_window = runner.calls_for("new-window")[0]
    assert new_window[new_window.index("-c") + 1] == str(directory)


def test_next_window_name_skips_existing_ai_windows(tmp_path: Path) -> None:
    runner = FakeTmuxRunner(windows=((1, "zsh"), (2, "ai"), (3, "ai2")))
    result = _launch(tmp_path, runner=runner)

    assert isinstance(result, TmuxAgentLaunch)
    assert result.window_name == "ai3"
    new_window = runner.calls_for("new-window")[0]
    assert new_window[new_window.index("-n") + 1] == "ai3"


def test_argv_elements_are_shell_quoted(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    entry = make_entry("claude", argv=("claude", "--title", "it's a test"))
    _launch(tmp_path, runner=runner, entry=entry)

    command = runner.calls_for("new-window")[0][-1]
    assert "clear; claude --title 'it'\"'\"'s a test'; tmux wait-for -S" in command


def test_tmux_missing_returns_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch_module, "tmux_available", lambda: False)
    result = _launch(tmp_path)

    assert isinstance(result, TmuxAgentLaunchError)
    assert result.code == "tmux_missing"
    assert "install tmux" in result.message


def test_not_inside_tmux_returns_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launch_module, "inside_tmux", lambda env=None: False)
    result = _launch(tmp_path)

    assert isinstance(result, TmuxAgentLaunchError)
    assert result.code == "not_inside_tmux"
    assert "start tmux" in result.message


def test_missing_directory_returns_typed_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = _launch(tmp_path, directory=missing)

    assert isinstance(result, TmuxAgentLaunchError)
    assert result.code == "directory_missing"
    assert str(missing) in result.message


def test_not_installed_returns_install_hint(tmp_path: Path) -> None:
    entry = make_entry("codex", installed=False, install_hint="npm i -g @openai/codex")
    result = _launch(tmp_path, entry=entry)

    assert isinstance(result, TmuxAgentLaunchError)
    assert result.code == "not_installed"
    assert result.message == "npm i -g @openai/codex"


def test_new_window_failure_returns_stderr(tmp_path: Path) -> None:
    runner = FakeTmuxRunner(new_window_error="sessions should be nested")
    result = _launch(tmp_path, runner=runner)

    assert isinstance(result, TmuxAgentLaunchError)
    assert result.code == "new_window_failed"
    assert "sessions should be nested" in result.message
    # Waiter is still registered first so the failure is after the scripted order.
    assert [call[1] for call in runner.calls] == [
        "list-windows",
        "run-shell",
        "new-window",
    ]


def test_mints_channel_when_not_supplied(tmp_path: Path) -> None:
    runner = FakeTmuxRunner()
    result = _launch(tmp_path, runner=runner, channel=None)

    assert isinstance(result, TmuxAgentLaunch)
    assert result.channel.startswith("sase-tmux-agent-")
    assert len(result.channel) == len("sase-tmux-agent-") + 12
    waiter = runner.calls_for("run-shell")[0][-1]
    assert result.channel in waiter
    command = runner.calls_for("new-window")[0][-1]
    assert f"tmux wait-for -S {result.channel}" in command
