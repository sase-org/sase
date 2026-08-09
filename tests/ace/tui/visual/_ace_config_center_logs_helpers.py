"""Logs tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sase.logs import (
    events_log_path,
    launch_failures_log_path,
    runs_log_path,
    toast_log,
    tui_log_path,
    tui_toasts_jsonl_path,
)

_FIXED_LOG_MTIME = int(datetime(2026, 6, 17, 14, 30, tzinfo=UTC).timestamp())


def _write_log(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (_FIXED_LOG_MTIME, _FIXED_LOG_MTIME))


def _seed_logs_tab_files() -> None:
    current_session = toast_log._reset_current_toast_session(
        session_started_at=datetime(2026, 6, 17, 14, 24, tzinfo=UTC),
        pid=4242,
    )
    assert current_session is not None
    _write_log(
        launch_failures_log_path(),
        "\n".join(
            [
                "=" * 72,
                "[2026-06-17 14:30:00 UTC] fanout launch failure: visual-auth",
                "  kind: fanout",
                "  project: sase",
                "  workspace: 11",
                "  error: RuntimeError: provider exited before writing metadata",
                "",
                "  traceback:",
                (
                    '    File "src/sase/ace/tui/actions/agent_workflow/'
                    '_launch_tasks.py", line 89, in _finish'
                ),
                "      raise RuntimeError('provider exited before writing metadata')",
                "    RuntimeError: provider exited before writing metadata",
                "",
                "  prompt preview:",
                "    Build the Logs tab visual snapshot and verify it is readable.",
            ]
        )
        + "\n",
    )
    _write_log(
        tui_log_path(),
        "\n".join(
            [
                "2026-06-17 14:28:00 WARNING sase.ace.tui: retrying stale launch task",
                (
                    "2026-06-17 14:30:00 ERROR sase.ace.tui: launch failed; "
                    "wrote launch_failures.log"
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        runs_log_path(),
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "260617_142700",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "FAILED",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "260617_143000",
                        "event": "agent_run",
                        "workflow": "visual",
                        "project": "sase",
                        "workspace_num": 11,
                        "status": "DONE",
                    }
                ),
            ]
        )
        + "\n",
    )
    _write_log(
        events_log_path(),
        json.dumps(
            {
                "timestamp": "260617_143000",
                "event": "agent_revive_failed",
                "project": "sase",
                "name": "visual-auth",
                "outcome": "failure",
            }
        )
        + "\n",
    )
    _write_log(
        tui_toasts_jsonl_path(),
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-06-16T22:03:12Z",
                        "session_id": "20260616T220100Z-98111",
                        "session_started_at": "2026-06-16T22:01:00Z",
                        "pid": 98111,
                        "severity": "warning",
                        "title": "",
                        "message": "ChangeSpec must be Ready to mail",  # legacy PNG text
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-16T22:15:33Z",
                        "session_id": "20260616T220100Z-98111",
                        "session_started_at": "2026-06-16T22:01:00Z",
                        "pid": 98111,
                        "severity": "information",
                        "title": "",
                        "message": "Saved query to slot 2",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T14:24:15Z",
                        "session_id": current_session.session_id,
                        "session_started_at": current_session.session_started_at,
                        "pid": current_session.pid,
                        "severity": "information",
                        "title": "",
                        "message": "Refreshing Agents from full history",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T14:24:31Z",
                        "session_id": current_session.session_id,
                        "session_started_at": current_session.session_started_at,
                        "pid": current_session.pid,
                        "severity": "information",
                        "title": "",
                        "message": "Refreshed",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T14:24:32Z",
                        "session_id": current_session.session_id,
                        "session_started_at": current_session.session_started_at,
                        "pid": current_session.pid,
                        "severity": "information",
                        "title": "",
                        "message": "Refreshed",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T14:25:47Z",
                        "session_id": current_session.session_id,
                        "session_started_at": current_session.session_started_at,
                        "pid": current_session.pid,
                        "severity": "warning",
                        "title": "",
                        "message": "PR is not set",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T14:26:03Z",
                        "session_id": current_session.session_id,
                        "session_started_at": current_session.session_started_at,
                        "pid": current_session.pid,
                        "severity": "error",
                        "title": "Workflow error",
                        "message": "provider exited before metadata\nretry queued",
                    }
                ),
            ]
        )
        + "\n",
    )
