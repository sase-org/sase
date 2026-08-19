"""Tests for applying the agent-window renumber plan."""

from __future__ import annotations

from sase.config.tmux_agent import TmuxAgentConfig
from sase.tmux_agent.renumber import renumber_agent_windows

from .fakes import FakeTmuxRunner


def test_renumber_issues_renames_for_gapped_windows() -> None:
    runner = FakeTmuxRunner(windows=((1, "ai"), (2, "ai3"), (3, "ai5")))
    count = renumber_agent_windows(config=TmuxAgentConfig(), runner=runner)

    assert count == 2
    assert runner.calls_for("rename-window") == [
        ["tmux", "rename-window", "-t", "2", "ai2"],
        ["tmux", "rename-window", "-t", "3", "ai3"],
    ]


def test_renumber_uses_index_order_when_names_are_reversed() -> None:
    runner = FakeTmuxRunner(windows=((9, "ai"), (4, "ai2"), (1, "ai3")))
    count = renumber_agent_windows(config=TmuxAgentConfig(), runner=runner)

    # Sorted by index: (1, ai3) -> ai, (4, ai2) stays, (9, ai) -> ai3.
    assert count == 2
    assert runner.calls_for("rename-window") == [
        ["tmux", "rename-window", "-t", "1", "ai"],
        ["tmux", "rename-window", "-t", "9", "ai3"],
    ]


def test_renumber_is_noop_when_already_correct() -> None:
    runner = FakeTmuxRunner(windows=((1, "ai"), (2, "ai2"), (3, "ai3")))
    count = renumber_agent_windows(config=TmuxAgentConfig(), runner=runner)

    assert count == 0
    assert runner.calls_for("rename-window") == []
    assert runner.calls_for("list-windows") == [
        ["tmux", "list-windows", "-F", "#{window_index}:#{window_name}"]
    ]


def test_renumber_is_noop_when_no_agent_windows() -> None:
    runner = FakeTmuxRunner(windows=((1, "zsh"), (2, "logs")))
    count = renumber_agent_windows(config=TmuxAgentConfig(), runner=runner)

    assert count == 0
    assert runner.calls_for("rename-window") == []


def test_renumber_honors_configured_window_name_base() -> None:
    runner = FakeTmuxRunner(windows=((1, "agent"), (2, "agent3")))
    count = renumber_agent_windows(
        config=TmuxAgentConfig(window_name="agent"),
        runner=runner,
    )

    assert count == 1
    assert runner.calls_for("rename-window") == [
        ["tmux", "rename-window", "-t", "2", "agent2"]
    ]
