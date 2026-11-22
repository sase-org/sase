"""Failure-aware session rollups stay aligned across Agents-tab surfaces."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest

from sase.agent.status_buckets import agent_status_bucket
from sase.ace.tui.models._agent_clan import clan_members, sase_agent_status_counts
from sase.ace.tui.models._agent_status_apply import apply_status_overrides
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from sase.ace.tui.models.failure_focus import FailureFocus
from sase.ace.tui.widgets.prompt_panel._agent_display_clan_roster import (
    clan_roster_entries,
)
from sase.core.agent_scan_wire_markers import (
    FinalizerStatusInstanceWire,
    FinalizerStatusSummaryWire,
)

_START = datetime(2026, 11, 22, 12, 0)
_NOW = _START + timedelta(hours=1)
_CaseFactory = Callable[[], tuple[Agent, tuple[Agent, ...]]]


def _row(
    name: str,
    status: str,
    *,
    minute: int,
    parent: str | None = None,
    role: str | None = None,
    bucket: str | None = None,
) -> Agent:
    start = _START + timedelta(minutes=minute)
    terminal = status in {"DONE", "FAILED", "NOT ADOPTED"}
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/failure-rollup.sase",
        status=status,
        status_bucket=bucket,
        start_time=start,
        run_start_time=start,
        stop_time=start + timedelta(minutes=1) if terminal else None,
        raw_suffix=f"suffix-{name}",
        parent_timestamp=parent,
        agent_name=name,
        agent_session="research.8",
        agent_session_role=role,
        agent_clan="research",
        agent_clan_generation="gen-1",
    )


def _session_root(*, status: str = "DONE", parallel: bool = False) -> Agent:
    root = _row("research.8", status, minute=0, role="root")
    root.agent_session_parallel = parallel
    return root


def _project(root: Agent, rows: tuple[Agent, ...]) -> tuple[Agent, Agent]:
    apply_status_overrides([root, *rows])
    projected = project_clan_tree([root, *rows])
    container = next(row for row in projected if row.is_clan_container)
    return container, root


def _assert_surfaces(
    container: Agent,
    root: Agent,
    *,
    expected_bucket: str,
    expected_wave_state: str,
) -> None:
    assert agent_status_bucket(root) == expected_bucket  # BY_STATUS source bucket

    members = clan_members(container)
    roster = clan_roster_entries(
        container,
        members,
        now=_NOW,
        digests=(),
    )
    root_entry = next(entry for entry in roster if entry.identity == root.identity)
    assert root_entry.effective_bucket == expected_bucket

    assert container.clan_waves is not None
    assert container.clan_waves.waves[0].state == expected_wave_state

    summary = build_agent_tribe_summary_snapshot(
        "epic",
        (container, *members),
        panel_collapsed=True,
        now=_NOW,
    )
    assert summary.units[0].status_bucket == expected_bucket

    counts = sase_agent_status_counts((container,), ())
    count_for_bucket = {
        "Failed": counts.failed,
        "Running": counts.running,
        "Done": counts.done,
    }[expected_bucket]
    assert count_for_bucket == 1


def _incident() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root()
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    failed = _row(
        "research.8--1",
        "FAILED",
        minute=1,
        parent=root.raw_suffix,
        role="attempt",
        bucket="Failed",
    )
    failed.finalizer_status = FinalizerStatusSummaryWire(
        phase="complete",
        status="failed",
        instances=[
            FinalizerStatusInstanceWire(
                id="commit",
                status="failed",
            )
        ],
    )
    held = _row(
        "research.8--mon-0",
        "NOT ADOPTED",
        minute=2,
        parent=failed.raw_suffix,
        role="monitor",
        bucket="Failed",
    )
    held.monitor_id = "monitor-0"
    held.monitor_state = "held"
    failed.runtime_children = [held]
    root.runtime_children = [failed]
    waiter = _row(
        "research.waiter",
        "WAITING",
        minute=3,
        role="root",
        bucket="Waiting",
    )
    waiter.agent_session = "research.waiter"
    waiter.waiting_for = ["research.8"]
    # The fixture projects one failed session plus its blocked direct member.
    root.runtime_children = [failed]
    return root, (failed, held, waiter)


def _retry_done() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root(status="FAILED")
    failed = _row(
        "research.8--first",
        "FAILED",
        minute=1,
        parent=root.raw_suffix,
        role="first",
        bucket="Failed",
    )
    retried = _row(
        "research.8--retry",
        "DONE",
        minute=3,
        parent=root.raw_suffix,
        role="retry",
        bucket="Done",
    )
    failed.retried_as_timestamp = retried.raw_suffix
    root.runtime_children = [failed, retried]
    return root, (failed, retried)


def _failed_monitor_with_continuation() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root()
    monitor = _row(
        "research.8--mon",
        "TESTED",
        minute=1,
        parent=root.raw_suffix,
        role="monitor",
        bucket="Failed",
    )
    monitor.monitor_id = "monitor"
    monitor.monitor_state = "failed"
    monitor.monitor_followup_outcome = "launched"
    continuation = _row(
        "research.8--next",
        "RUNNING",
        minute=3,
        parent=root.raw_suffix,
        role="continuation",
        bucket="Running",
    )
    root.runtime_children = [monitor, continuation]
    return root, (monitor, continuation)


def _plain_root_failure() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root()
    failed = _row(
        "research.8--last",
        "FAILED",
        minute=1,
        parent=root.raw_suffix,
        role="last",
        bucket="Failed",
    )
    root.runtime_children = [failed]
    return root, (failed,)


def _parallel_failure() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root(parallel=True)
    failed = _row(
        "research.8--peer",
        "FAILED",
        minute=1,
        parent=root.raw_suffix,
        role="peer",
        bucket="Failed",
    )
    failed.agent_session_parallel = True
    root.runtime_children = [failed]
    return root, (failed,)


def _healthy_running() -> tuple[Agent, tuple[Agent, ...]]:
    root = _session_root(status="RUNNING")
    root.status_bucket = "Running"
    root.stop_time = None
    return root, ()


@pytest.mark.parametrize(
    ("build_case", "expected_bucket", "expected_wave_state"),
    (
        (_incident, "Failed", "failed"),
        (_retry_done, "Done", "done"),
        (_failed_monitor_with_continuation, "Running", "in_flight"),
        (_plain_root_failure, "Failed", "failed"),
        (_parallel_failure, "Failed", "failed"),
        (_healthy_running, "Running", "in_flight"),
    ),
)
def test_failure_rollup_agrees_across_agent_surfaces(
    build_case: _CaseFactory,
    expected_bucket: str,
    expected_wave_state: str,
) -> None:
    root, rows = build_case()
    container, root = _project(root, rows)

    _assert_surfaces(
        container,
        root,
        expected_bucket=expected_bucket,
        expected_wave_state=expected_wave_state,
    )

    if expected_bucket == "Failed":
        assert isinstance(root.failure_focus, FailureFocus)
        assert isinstance(container.failure_focus, FailureFocus)
    else:
        assert root.failure_focus is None
        assert container.failure_focus is None


def test_incident_failure_focus_has_finalizer_handoff_and_blocker() -> None:
    root, rows = _incident()
    container, root = _project(root, rows)

    assert root.status == "FAILED"
    focus = container.failure_focus
    assert isinstance(focus, FailureFocus)
    assert focus.member_label == ".8"
    assert focus.failed_row.name == "research.8--1"
    assert focus.finalizer_chip == "⊛✗ commit"
    assert focus.finalizer_chip_style == "bold #FF5F5F"
    assert focus.failed_row.duration_seconds == 60.0
    assert focus.not_adopted is not None
    assert focus.not_adopted.name == "research.8--mon-0"
    assert focus.not_adopted.kind == "monitor"
    assert focus.not_adopted.starter_name == "research.8--1"
    assert focus.blocked == (".waiter",)


def test_session_tribe_unit_uses_the_root_rollup_bucket() -> None:
    root, rows = _plain_root_failure()
    apply_status_overrides([root, *rows])

    snapshot = build_agent_tribe_summary_snapshot(
        "epic",
        (root,),
        panel_collapsed=True,
        now=_NOW,
    )

    assert root.status == "FAILED"
    assert snapshot.units[0].kind == "session"
    assert snapshot.units[0].status_bucket == agent_status_bucket(root) == "Failed"
    assert snapshot.status_bucket == "Failed"
    assert snapshot.counts.failed == 1
