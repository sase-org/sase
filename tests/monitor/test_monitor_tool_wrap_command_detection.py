"""Command shape detection used by zero-weight monitor validation."""

from __future__ import annotations

import pytest

from sase.monitor.tool_wrap import command_invokes_tool_run


@pytest.mark.parametrize(
    "command",
    [
        "sase tool run check",
        "/usr/bin/sase tool run -- x",
        "python -m sase tool run check",
        "sleep 5 && sase tool run check",
    ],
)
def test_detects_sase_tool_run_shapes(command: str) -> None:
    assert command_invokes_tool_run(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "sleep 300",
        "gh run watch 1 --exit-status",
        "tool run x",
        "sase tool run 'unbalanced",
    ],
)
def test_non_tool_run_or_unparseable_commands_are_false(command: str) -> None:
    assert command_invokes_tool_run(command) is False
