"""CLI contract tests for ``sase axe status``."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

import sase.axe.status_collector as status_collector
from sase.axe.status_models import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeLifecycleEvent,
    AxeLumberjackStatus,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusSnapshot,
)
from sase.main.axe_handler import handle_axe_command
from sase.main.parser import create_parser


def _missing_process() -> AxeProcessObservation:
    return AxeProcessObservation(pid=None, live=None)


def _orchestrator(*, coherent: bool = True) -> AxeOrchestratorStatus:
    missing = _missing_process()
    if not coherent:
        return AxeOrchestratorStatus(
            state="incoherent",
            coherence="incoherent",
            live_pids=(123, 124),
            lifecycle_lock_held=True,
            lock_holder=AxeProcessObservation(pid=123, live=True),
            orchestrator_pid_file=AxeProcessObservation(pid=124, live=True),
            legacy_pid_file=missing,
        )
    return AxeOrchestratorStatus(
        state="running",
        coherence="coherent",
        live_pids=(123,),
        lifecycle_lock_held=True,
        lock_holder=AxeProcessObservation(pid=123, live=True),
        orchestrator_pid_file=AxeProcessObservation(pid=123, live=True),
        legacy_pid_file=missing,
    )


def _lumberjack(
    *,
    name: str = "hooks",
    state: str = "running",
    configured: bool = True,
) -> AxeLumberjackStatus:
    return AxeLumberjackStatus(
        name=name,
        state=state,  # type: ignore[arg-type]
        stale_threshold_seconds=90,
        configured=configured,
        interval_seconds=20 if configured else None,
        configured_chops=("alpha_check", "beta_check") if configured else (),
        recorded_pid=456,
        reported_state="running",
        process_live=True,
        started_at="2026-07-23T10:00:00+00:00",
        start_age_seconds=7200,
        heartbeat_at="2026-07-23T11:59:15+00:00",
        heartbeat_age_seconds=45,
        cycles_run=17,
        errors_encountered=3,
        uptime_seconds=7190,
    )


def _snapshot() -> AxeStatusSnapshot:
    return AxeStatusSnapshot(
        schema_version=AXE_STATUS_WIRE_SCHEMA_VERSION,
        generated_at="2026-07-23T12:00:00+00:00",
        state="running",
        health="healthy",
        summary="AXE is running normally.",
        exit_code=0,
        desired_state=AxeDesiredStateRecord(
            state="running",
            source="test fixture",
            timestamp="2026-07-23T09:00:00+00:00",
        ),
        orchestrator=_orchestrator(),
        maintenance=None,
        hook_runners=AxeRunnerOccupancy(current=1, maximum=3),
        agent_runners=AxeRunnerOccupancy(current=2, maximum=4),
        lumberjacks=(_lumberjack(),),
        latest_lifecycle_event=AxeLifecycleEvent(
            event="start",
            timestamp="2026-07-23T10:00:00+00:00",
            source="test fixture",
            outcome="started",
            success=True,
            reason=None,
            orchestrator_pid=123,
            age_seconds=7200,
        ),
        issues=(),
        collection_error=None,
    )


def test_parser_exposes_status_and_both_json_aliases() -> None:
    short = create_parser().parse_args(["axe", "status", "-j"])
    long = create_parser().parse_args(["axe", "status", "--json"])

    assert short.axe_subcommand == "status"
    assert short.json is True
    assert long.json is True


@pytest.mark.parametrize("json_mode", [False, True])
def test_handler_delegates_status_to_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    json_mode: bool,
) -> None:
    import sase.main.scheduler_handler as scheduler_handler

    seen: list[argparse.Namespace] = []

    def fake_handle(args: argparse.Namespace) -> None:
        seen.append(args)
        raise SystemExit(0)

    monkeypatch.setattr(scheduler_handler, "handle_scheduler_command", fake_handle)

    with pytest.raises(SystemExit):
        handle_axe_command(
            argparse.Namespace(
                axe_subcommand="status",
                json=json_mode,
                vcs_provider=None,
            )
        )

    assert len(seen) == 1
    assert seen[0].scheduler_subcommand == "status"
    assert seen[0].json is json_mode


def test_status_collector_validation_uses_public_routine_job_terms() -> None:
    config = SimpleNamespace(
        max_hook_runners=1,
        max_agent_runners=1,
        lumberjacks={"checks": SimpleNamespace(interval=5, chop_names=["", "smoke"])},
    )

    with pytest.raises(ValueError) as exc_info:
        status_collector._validate_config(config)  # noqa: SLF001

    message = str(exc_info.value)
    assert message == "AXE routine 'checks' has invalid enabled job names"
    assert "lumberjack" not in message
    assert "chop names" not in message
