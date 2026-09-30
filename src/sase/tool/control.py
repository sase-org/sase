"""``sase tool stop`` and ``sase tool wait`` lifecycle controls.

Both commands are ownership-aware facades over a run's execution owner:
a hand-off run stops through its proc or monitor owner, an inline run
signals only its identity-matched wrapper, and a nested foreground run
is refused with a pointer to the owner that must be stopped instead.

This module is a facade: the stop, wait, and output-path implementations
live in the ``sase.tool.control_*`` siblings (with shared run-lookup
helpers in the private ``sase.tool._control_shared`` module). Import the
public names from here, never from the siblings directly.
"""

from __future__ import annotations

from sase.tool._control_shared import (
    TERMINAL_RUN_STATES as TERMINAL_RUN_STATES,
    UNSETTLED_RUN_STATES as UNSETTLED_RUN_STATES,
    UnknownRunError as UnknownRunError,
)
from sase.tool.control_outputs import (
    monitor_output_path as monitor_output_path,
    output_paths_for_run as output_paths_for_run,
)
from sase.tool.control_stop import (
    OwnerStopResult as OwnerStopResult,
    ToolStopCliRequest as ToolStopCliRequest,
    handle_stop as handle_stop,
    stop_run_through_owner as stop_run_through_owner,
)
from sase.tool.control_wait import (
    ToolWaitCliRequest as ToolWaitCliRequest,
    handle_wait as handle_wait,
    wait_for_settlement as wait_for_settlement,
)


__all__ = [
    "OwnerStopResult",
    "UnknownRunError",
    "ToolStopCliRequest",
    "ToolWaitCliRequest",
    "handle_stop",
    "handle_wait",
    "monitor_output_path",
    "output_paths_for_run",
    "stop_run_through_owner",
    "wait_for_settlement",
]
