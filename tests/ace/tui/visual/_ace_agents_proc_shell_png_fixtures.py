"""Stand-alone proc-shell fixtures for Agents-tab PNG visual snapshots.

`%proc` launch units surface in the Agents tab as presentation-only rows backed
by the proc store, never as agents. These fixtures seed a deterministic observer
projection so the goldens can show the row glyph, derived titles, Bash/Python
badges, and every active and terminal state next to ordinary agent rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.procs import PROC_LIFECYCLE_PROC_SHELL, XPROMPT_PROC_ORIGIN

PROC_SHELL_VISUAL_NOW = datetime(2026, 8, 20, 12, 30, 0)

_PROJECT_FILE = "/workspace/sase/visual_project.sase"
_ACTIVE_PROC_STATUSES = frozenset({"pending", "running", "settling"})


class _NoopProcObserver:
    """Stand-in observer so the seeded projection is never overwritten."""

    def request_poll(self) -> None:
        return None

    def set_detail_proc(self, proc_id: str | None) -> None:
        del proc_id

    def stop(self, *, timeout: float = 1.0) -> None:
        del timeout


def _proc_shell_row(
    proc_id: str,
    *,
    label: str,
    status: str,
    phase: str,
    language: str,
    age_seconds: int,
    shell_name: str | None = None,
    preview: str,
    output: str = "",
    waits: list[Any] | None = None,
    condition_result: dict[str, str] | None = None,
    logical_id: str = "unit-1",
    record_label: bool = True,
) -> ObservedProc:
    started_at = PROC_SHELL_VISUAL_NOW - timedelta(seconds=age_seconds)
    return ObservedProc(
        proc_id=proc_id,
        proc_type="command",
        cl_name="sase",
        project_file="",
        status=status,
        message="",
        started_at=started_at,
        finished_at=None if status in _ACTIVE_PROC_STATUSES else started_at,
        display_name=label,
        command=[language, f"sha256:{proc_id}"],
        cwd="/workspace/sase",
        origin=XPROMPT_PROC_ORIGIN,
        log_path=f"/tmp/{proc_id}.log",
        lifecycle=PROC_LIFECYCLE_PROC_SHELL,
        project="sase",
        workspace_num=12,
        phase=phase,
        shell_name=shell_name,
        shell_kind=language,
        timeout_seconds=1200,
        idle_timeout_seconds=300,
        request_fingerprint=f"sha256:{proc_id}",
        supervisor_id="supervisor-1",
        output=output,
        xprompt_proc={
            "logical_id": logical_id,
            "label": label if record_label else None,
            "shell_name": shell_name,
            "code_digest": f"sha256:{proc_id}",
            "code_language": language,
            "safe_preview": preview,
            "waits": waits if waits is not None else [],
            "condition_result": condition_result,
        },
    )


def proc_shell_visual_rows() -> tuple[ObservedProc, ...]:
    """Stand-alone `%proc` rows across both languages and every state class."""
    return (
        _proc_shell_row(
            "a1b2c3d4e5f6",
            label="Scoped verification for the typed launch matrix",
            status="running",
            phase="running",
            language="bash",
            age_seconds=95,
            shell_name="verify",
            preview="just check",
            output="ruff .................. Passed\nmypy .................. Passed\n",
            waits=[{"kind": "unit", "target": "unit-1"}],
            condition_result={"status": "eligible", "reason": "exit 0"},
        ),
        _proc_shell_row(
            "b2c3d4e5f607",
            label="Warm the docs cache",
            status="settling",
            phase="settling",
            language="python",
            age_seconds=240,
            preview="print('ready')",
            output="cache warm\n",
        ),
        _proc_shell_row(
            "c3d4e5f60718",
            label="Publish preview site",
            status="success",
            phase="settled",
            language="python",
            age_seconds=930,
            shell_name="publish",
            preview="build_site()",
            output="wrote 42 pages\n",
        ),
        _proc_shell_row(
            "d4e5f6071829",
            label="Contract regression sweep",
            status="error",
            phase="settled",
            language="bash",
            age_seconds=1500,
            preview="just test-scoped",
            output="1 failed, 3820 passed\n",
        ),
        _proc_shell_row(
            "e5f607182930",
            label="Nightly index rebuild",
            status="killed",
            phase="settled",
            language="bash",
            age_seconds=2400,
            preview="sase index rebuild",
            output="interrupted\n",
        ),
        _proc_shell_row(
            "f60718293041",
            label="unit-1",
            status="success",
            phase="running",
            language="bash",
            age_seconds=3100,
            shell_name=None,
            preview="echo hello && sleep 30 && echo world",
            output="hello\nworld\n",
            logical_id="unit-1",
            record_label=False,
        ),
        _proc_shell_row(
            "071829304152",
            label="unit-2",
            status="running",
            phase="running",
            language="bash",
            age_seconds=45,
            shell_name=None,
            preview=(
                "echo alpha beta gamma delta epsilon zeta eta theta iota kappa\n"
                "echo lambda mu nu xi omicron"
            ),
            output="alpha beta gamma\n",
            logical_id="unit-2",
            record_label=False,
        ),
    )


def proc_shell_visual_agents() -> list[Agent]:
    """Ordinary agents that share the tab so grouping stays visible."""
    started = PROC_SHELL_VISUAL_NOW - timedelta(minutes=6)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-typed-launch",
            project_file=_PROJECT_FILE,
            status="RUNNING",
            start_time=started,
            raw_suffix="20260820-122400-typed-launch",
            agent_name="typed.launch",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-admission",
            project_file=_PROJECT_FILE,
            status="WAITING",
            start_time=started + timedelta(minutes=1),
            raw_suffix="20260820-122500-admission",
            agent_name="admission",
        ),
    ]


def patch_proc_shell_project_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin project display names so the projection performs no config I/O."""
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_proc_shells.project_display_name_for",
        lambda key: str(key),
    )


def seed_proc_shell_projection(app: Any) -> None:
    """Install the deterministic proc-shell projection on a running app."""
    observer = getattr(app, "_proc_observer", None)
    stop = getattr(observer, "stop", None)
    if callable(stop):
        stop()
    app._proc_observer = _NoopProcObserver()
    rows = proc_shell_visual_rows()
    app._proc_projection = ProcProjection(
        rows=rows,
        active_count=sum(1 for row in rows if row.status in _ACTIVE_PROC_STATUSES),
        active_monitor_count=0,
        session_id="session-visual",
    )
    app._sync_proc_shell_agents_from_projection()
