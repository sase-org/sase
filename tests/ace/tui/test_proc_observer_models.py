"""Tests for ACE proc observer projections and row models."""

from __future__ import annotations

from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcProjection,
    compose_proc_projection,
    proc_projection_for,
)
from sase.core.time import local_now


def test_projection_detects_active_scope_conflicts() -> None:
    running = ObservedProc(
        proc_id="run",
        proc_type="patch",
        cl_name="demo",
        project_file="project.sase",
        status="running",
        message="running",
        started_at=local_now(),
        exclusive_scopes=frozenset({"ace:patch:demo"}),
    )
    done = ObservedProc(
        proc_id="done",
        proc_type="patch",
        cl_name="demo",
        project_file="project.sase",
        status="success",
        message="done",
        started_at=local_now(),
        exclusive_scopes=frozenset({"ace:patch:done"}),
    )

    projection = ProcProjection(rows=(done, running), active_count=1)

    assert projection.scope_conflict({"ace:patch:demo"}) is running
    assert projection.scope_conflict({"ace:patch:done"}) is None


def test_projection_scope_includes_unattributed_rows() -> None:
    mine = ObservedProc(
        proc_id="mine",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="mine",
        started_at=local_now(),
        session_id="session-a",
    )
    unattributed = ObservedProc(
        proc_id="unattributed",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="unattributed",
        started_at=local_now(),
        session_id=None,
    )
    other = ObservedProc(
        proc_id="other",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="other",
        started_at=local_now(),
        session_id="session-b",
    )
    projection = ProcProjection(
        rows=(mine, unattributed, other),
        active_count=3,
        session_id="session-a",
    )

    assert projection.scoped_rows(all_sessions=False) == [mine, unattributed]
    assert projection.scoped_rows(all_sessions=True) == [mine, unattributed, other]


def test_compose_proc_projection_attributes_and_counts_session_rows() -> None:
    durable = ObservedProc(
        proc_id="durable",
        proc_type="patch",
        cl_name="demo",
        project_file="",
        status="running",
        message="durable",
        started_at=local_now(),
        session_id="session-a",
    )
    local = ObservedProc(
        proc_id="session-1",
        proc_type="sync",
        cl_name="",
        project_file="",
        status="running",
        message="local",
        started_at=local_now(),
    )
    projection = compose_proc_projection(
        ProcProjection(rows=(durable,), active_count=1, session_id="session-a"),
        (local,),
    )

    assert projection.active_count == 2
    assert projection.session_id == "session-a"
    local_row = next(row for row in projection.rows if row.proc_id == "session-1")
    assert local_row.session_id == "session-a"
    assert local_row.session_live is True


def test_proc_projection_for_prefers_effective_method() -> None:
    durable = ProcProjection(session_id="ignored")
    effective = ProcProjection(session_id="effective", active_count=2)
    app = type(
        "_App",
        (),
        {
            "_proc_projection": durable,
            "_effective_proc_projection": lambda self: effective,
        },
    )()

    assert proc_projection_for(app) is effective
    assert proc_projection_for(type("_Bare", (), {})()) == ProcProjection()


def test_projection_scope_keeps_dead_session_rows_visible_but_inactive() -> None:
    mine = ObservedProc(
        proc_id="mine",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="mine",
        started_at=local_now(),
        session_id="session-a",
        session_live=True,
    )
    dead = ObservedProc(
        proc_id="dead",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="dead",
        started_at=local_now(),
        session_id="session-dead",
        session_live=False,
    )
    unattributed = ObservedProc(
        proc_id="unattributed",
        proc_type="command",
        cl_name="",
        project_file="",
        status="settling",
        message="unattributed",
        started_at=local_now(),
        session_id=None,
    )
    other = ObservedProc(
        proc_id="other",
        proc_type="command",
        cl_name="",
        project_file="",
        status="pending",
        message="other",
        started_at=local_now(),
        session_id="session-b",
        session_live=True,
    )
    projection = ProcProjection(
        rows=(mine, dead, unattributed, other),
        session_id="session-a",
    )

    assert projection.scoped_rows(all_sessions=False) == [mine, dead, unattributed]
    assert projection.active_rows() == [mine, unattributed]
    assert projection.active_rows(all_sessions=True) == [mine, unattributed, other]


def test_active_monitor_rows_filters_active_rows_by_origin() -> None:
    ace_row = ObservedProc(
        proc_id="ace",
        proc_type="command",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="ace",
    )
    monitor_row = ObservedProc(
        proc_id="monitor",
        proc_type="detached",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="monitor",
    )
    projection = ProcProjection(rows=(ace_row, monitor_row))

    assert [row.proc_id for row in projection.active_rows()] == ["ace", "monitor"]
    assert [row.proc_id for row in projection.active_monitor_rows()] == ["monitor"]


def test_compose_proc_projection_counts_monitor_rows_and_keeps_overlay_rows_blue() -> (
    None
):
    durable_monitor = ObservedProc(
        proc_id="durable-monitor",
        proc_type="detached",
        cl_name="",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
        origin="monitor",
    )
    durable = ProcProjection(
        rows=(durable_monitor,),
        active_count=1,
        active_monitor_count=1,
        session_id="session-a",
    )
    # Session-local overlay rows are ACE-owned by construction and default to
    # origin="", so they must stay counted on the blue (non-monitor) side.
    overlay = ObservedProc(
        proc_id="overlay",
        proc_type="command",
        cl_name="demo",
        project_file="",
        status="running",
        message="",
        started_at=local_now(),
    )

    projection = compose_proc_projection(durable, [overlay])

    assert projection.active_count == 2
    assert projection.active_monitor_count == 1
