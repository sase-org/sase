"""Command-line proc tag and retention bucket constants."""

from __future__ import annotations

from sase.procs import (
    COMMAND_LINE_PROC_HISTORY_LIMIT,
    COMMAND_LINE_PROC_TAG,
)
from sase.procs.command_line import (
    COMMAND_LINE_PROC_HISTORY_LIMIT as MODULE_HISTORY_LIMIT,
)
from sase.procs.command_line import COMMAND_LINE_PROC_TAG as MODULE_TAG


def test_command_line_proc_tag_value() -> None:
    assert COMMAND_LINE_PROC_TAG == "command-line"
    assert MODULE_TAG == "command-line"


def test_command_line_proc_history_limit_value() -> None:
    assert COMMAND_LINE_PROC_HISTORY_LIMIT == 50
    assert MODULE_HISTORY_LIMIT == 50
