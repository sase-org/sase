from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sase.agent.wait_watch import (
    WaitSettlementOutcome,
    WaitState,
    WaitWatchConfig,
    classify_wait_targets,
    resolve_wait_targets,
    watch_wait_targets,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    FamilyShellWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    WaitingMarkerWire,
)


def _snapshot(*records: AgentArtifactRecordWire) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=list(records),
    )


def _record(
    timestamp: str,
    *,
    name: str,
    pid: int | None = None,
    outcome: str | None = None,
    done_family_shell: FamilyShellWire | None = None,
    family: str | None = None,
    parent_timestamp: str | None = None,
    clan: str | None = None,
    clan_generation: str | None = None,
    waiting: WaitingMarkerWire | None = None,
    pending_question: PendingQuestionMarkerWire | None = None,
    plan_path: str | None = None,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="sase",
        project_dir="/tmp/sase/projects/sase",
        project_file="/tmp/sase/projects/sase/sase.gp",
        workflow_dir_name="ace-run",
        artifact_dir=f"/tmp/sase/projects/sase/artifacts/ace-run/{timestamp}",
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            pid=pid,
            agent_family=family,
            workflow_name=family,
            parent_timestamp=parent_timestamp,
            agent_clan=clan,
            agent_clan_generation=clan_generation,
            run_started_at="2026-08-23T12:00:00Z" if pid is not None else None,
        ),
        done=DoneMarkerWire(outcome=outcome, family_shell=done_family_shell)
        if outcome is not None
        else None,
        waiting=waiting,
        pending_question=pending_question,
        plan_path=PlanPathMarkerWire(plan_path=plan_path) if plan_path else None,
        has_done_marker=outcome is not None,
    )


def _live_if_pid(meta: dict[str, object], _artifact_dir: Path) -> bool:
    return isinstance(meta.get("pid"), int)


def _clock(values: list[float]) -> Iterator[float]:
    yield from values
    while True:
        yield values[-1]


def test_wait_watch_classifies_success_and_failure() -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="good", outcome="completed"),
        _record("20260823120001", name="bad", outcome="failed"),
    )

    targets = resolve_wait_targets(
        ["good", "bad"],
        snapshot,
        liveness_checker=_live_if_pid,
    )
    states = classify_wait_targets(
        targets,
        snapshot,
        liveness_checker=_live_if_pid,
    )

    assert [state.state for state in states] == [
        WaitState.SUCCEEDED,
        WaitState.FAILED,
    ]


def test_wait_watch_classifies_settled_gate_as_success() -> None:
    snapshot = _snapshot(
        _record(
            "20260827120000",
            name="approval--gate",
            outcome="gated",
            done_family_shell=FamilyShellWire(kind="gate", state="answered"),
        )
    )

    target = resolve_wait_targets(
        ["approval--gate"],
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]
    state = classify_wait_targets(
        (target,),
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]

    assert state.state is WaitState.SUCCEEDED
    assert state.members[0].outcome == "completed"


def test_wait_watch_family_target_includes_late_successor() -> None:
    root_running = _record(
        "20260823120000", name="deploy--plan", pid=123, family="deploy"
    )
    target = resolve_wait_targets(
        ["deploy"],
        _snapshot(root_running),
        liveness_checker=_live_if_pid,
    )[0]
    root_done = _record(
        "20260823120000", name="deploy--plan", outcome="completed", family="deploy"
    )
    late_child = _record(
        "20260823120001",
        name="deploy--code",
        pid=456,
        family="deploy",
        parent_timestamp="20260823120000",
    )

    states = classify_wait_targets(
        (target,),
        _snapshot(root_done, late_child),
        liveness_checker=_live_if_pid,
    )

    assert states[0].state is WaitState.RUNNING
    assert [member.name for member in states[0].members] == [
        "deploy--plan",
        "deploy--code",
    ]


def test_wait_watch_clan_aggregates_generation_members() -> None:
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="review.a",
            outcome="completed",
            clan="review",
            clan_generation="g1",
        ),
        _record(
            "20260823120001",
            name="review.b",
            pid=123,
            clan="review",
            clan_generation="g1",
        ),
    )

    target = resolve_wait_targets(
        ["review"],
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]
    state = classify_wait_targets(
        (target,),
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]

    assert state.state is WaitState.RUNNING
    assert [member.name for member in state.members] == ["review.a", "review.b"]


def test_wait_watch_settles_terminal_target_immediately_without_sleep() -> None:
    snapshot = _snapshot(_record("20260823120000", name="done", outcome="completed"))
    target = resolve_wait_targets(["done"], snapshot, liveness_checker=_live_if_pid)[0]
    sleeps: list[float] = []
    clock = _clock([10.0, 10.0])

    ticks = list(
        watch_wait_targets(
            WaitWatchConfig(targets=(target,)),
            lambda: snapshot,
            clock=lambda: next(clock),
            sleep=sleeps.append,
            liveness_checker=_live_if_pid,
        )
    )

    assert len(ticks) == 1
    assert ticks[0].settlement is not None
    assert ticks[0].settlement.outcome is WaitSettlementOutcome.SUCCEEDED
    assert sleeps == []


def test_wait_watch_classifies_dead_plan_as_needs_review() -> None:
    snapshot = _snapshot(
        _record(
            "20260823120000",
            name="planner",
            plan_path="/tmp/sase/plan.md",
        )
    )

    target = resolve_wait_targets(["planner"], snapshot, liveness_checker=_live_if_pid)[
        0
    ]
    state = classify_wait_targets(
        (target,),
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]

    assert state.state is WaitState.NEEDS_REVIEW


def test_wait_watch_classifies_dead_unmarked_agent_as_stalled() -> None:
    snapshot = _snapshot(_record("20260823120000", name="lost"))

    target = resolve_wait_targets(["lost"], snapshot, liveness_checker=_live_if_pid)[0]
    state = classify_wait_targets(
        (target,),
        snapshot,
        liveness_checker=_live_if_pid,
    )[0]

    assert state.state is WaitState.STALLED


def test_wait_watch_wait_blocked_continues_until_blocked_target_completes() -> None:
    blocked = _snapshot(
        _record(
            "20260823120000",
            name="planner",
            plan_path="/tmp/sase/plan.md",
        )
    )
    done = _snapshot(_record("20260823120000", name="planner", outcome="completed"))
    target = resolve_wait_targets(["planner"], blocked, liveness_checker=_live_if_pid)[
        0
    ]
    snapshots = iter([blocked, done])
    sleeps: list[float] = []
    clock = _clock([0.0, 0.0, 1.0])

    ticks = list(
        watch_wait_targets(
            WaitWatchConfig(
                targets=(target,),
                interval_seconds=0.25,
                wait_blocked=True,
            ),
            lambda: next(snapshots),
            clock=lambda: next(clock),
            sleep=sleeps.append,
            liveness_checker=_live_if_pid,
        )
    )

    assert [tick.target_states[0].state for tick in ticks] == [
        WaitState.NEEDS_REVIEW,
        WaitState.SUCCEEDED,
    ]
    assert ticks[-1].settlement is not None
    assert ticks[-1].settlement.outcome is WaitSettlementOutcome.SUCCEEDED
    assert sleeps == [0.25]


def test_wait_watch_times_out_pending_target() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=123))
    target = resolve_wait_targets(["runner"], snapshot, liveness_checker=_live_if_pid)[
        0
    ]
    sleeps: list[float] = []
    clock = _clock([0.0, 0.0, 3.0])

    ticks = list(
        watch_wait_targets(
            WaitWatchConfig(
                targets=(target,), interval_seconds=1.0, timeout_seconds=3.0
            ),
            lambda: snapshot,
            clock=lambda: next(clock),
            sleep=sleeps.append,
            liveness_checker=_live_if_pid,
        )
    )

    assert ticks[-1].settlement is not None
    assert ticks[-1].settlement.outcome is WaitSettlementOutcome.TIMEOUT
    assert sleeps == [1.0]


def test_wait_watch_settlement_precedence() -> None:
    cases: list[tuple[list[AgentArtifactRecordWire], WaitSettlementOutcome]] = [
        (
            [
                _record("20260823120000", name="bad", outcome="failed"),
                _record("20260823120001", name="blocked", plan_path="/tmp/plan.md"),
            ],
            WaitSettlementOutcome.FAILED,
        ),
        (
            [_record("20260823120000", name="blocked", plan_path="/tmp/plan.md")],
            WaitSettlementOutcome.BLOCKED,
        ),
        (
            [_record("20260823120000", name="runner", pid=123)],
            WaitSettlementOutcome.TIMEOUT,
        ),
    ]

    for records, expected in cases:
        snapshot = _snapshot(*records)
        targets = resolve_wait_targets(
            [
                record.agent_meta.name
                for record in records
                if record.agent_meta is not None and record.agent_meta.name is not None
            ],
            snapshot,
            liveness_checker=_live_if_pid,
        )
        clock = _clock([0.0, 0.0])
        tick = next(
            watch_wait_targets(
                WaitWatchConfig(targets=targets, timeout_seconds=0.0),
                lambda snapshot=snapshot: snapshot,
                clock=lambda clock=clock: next(clock),
                sleep=lambda _seconds: None,
                liveness_checker=_live_if_pid,
            )
        )

        assert tick.settlement is not None
        assert tick.settlement.outcome is expected
