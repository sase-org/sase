"""Shared fixtures for chop action lifecycle tests."""

from __future__ import annotations

from sase.axe.chop_agents import _record_chop_agent_launch
from sase.axe.state import ChopRunEntry, finish_chop_run, start_chop_run


def launched_entry(
    run_id: str,
    *,
    pid: int,
    launches: list[dict[str, object]] | None = None,
    script_duration_ms: int | None = None,
    typed_admission: dict[str, object] | None = None,
) -> ChopRunEntry:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name="docs",
        chop_name="docs",
        started_at="2026-07-18T12:00:00+00:00",
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(entry)
    finish_chop_run(
        "docs",
        "docs",
        run_id,
        status="launched",
        finished_at=None,
        duration_ms=1,
        exit_code=0,
        agent_pid=pid,
        launches=[{"pid": pid}] if launches is None else launches,
        typed_admission=typed_admission,
        script_duration_ms=script_duration_ms,
    )
    return entry


def record_agent(
    run_id: str,
    *,
    pid: int,
    timestamp: str = "260718_120000",
    admission_logical_id: str = "",
    admission_fingerprint: str = "",
    proposal_index: int | None = None,
    proposal_id: str = "",
) -> object:
    return _record_chop_agent_launch(
        lumberjack_name="docs",
        chop_name="docs",
        run_id=run_id,
        pid=pid,
        project_file="/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=1,
        workflow_name="ace(run)-260718_120000",
        cl_name="sase",
        timestamp=timestamp,
        prompt="refresh",
        admission_logical_id=admission_logical_id,
        admission_fingerprint=admission_fingerprint,
        proposal_index=proposal_index,
        proposal_id=proposal_id,
    )
