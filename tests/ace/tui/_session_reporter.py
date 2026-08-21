"""Shared session-local reporter factory for ACE proc tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.proc_observer import ObservedProc
from sase.ace.tui.session_proc_reporter import SessionProcReporter

_STARTED = datetime(2026, 8, 21, 12, 0, 0)


def session_reporter(*, proc_type: str = "test") -> SessionProcReporter:
    """Return a real session reporter wrapping a running presentation row."""
    return SessionProcReporter(
        ObservedProc(
            proc_id="session-test",
            proc_type=proc_type,
            cl_name="",
            project_file="",
            status="running",
            message="running",
            started_at=_STARTED,
            display_name=proc_type,
        )
    )
