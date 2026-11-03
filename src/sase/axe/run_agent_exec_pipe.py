"""Pipe marker handling for the agent execution loop.

This module preserves the historical
``sase.axe.run_agent_exec_pipe`` import surface while the
implementation lives in smaller focused modules.
"""

from sase.axe.run_agent_exec_pipe_handoff import (
    handle_staged_pipe_marker,
    restore_staged_pipe_successor,
)

__all__ = [
    "handle_staged_pipe_marker",
    "restore_staged_pipe_successor",
]
