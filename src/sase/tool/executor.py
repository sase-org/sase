"""Foreground ToolRun executor: begin-before-spawn, two pumps, fail-open.

Facade preserving the original ``sase.tool.executor`` import path. The
implementation lives in the split ``executor_*`` modules; this module only
re-exports the public names.
"""

from __future__ import annotations

from sase.tool.executor_continuation import agent_default_continuation_mode
from sase.tool.executor_entry import execute_tool_run
from sase.tool.executor_models import RecordedRunContext, ToolRunCliRequest
from sase.tool.executor_run import run_recorded_body


__all__ = [
    "RecordedRunContext",
    "ToolRunCliRequest",
    "agent_default_continuation_mode",
    "execute_tool_run",
    "run_recorded_body",
]
