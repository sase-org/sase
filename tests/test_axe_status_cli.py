"""CLI contract and terminal rendering tests for ``sase axe status``."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

import sase.axe.status_collector as status_collector
import sase.axe.status_render as status_render
from sase.axe.status_models import (
    AXE_STATUS_WIRE_SCHEMA_VERSION,
    AxeDesiredStateRecord,
    AxeLifecycleEvent,
    AxeLumberjackStatus,
    AxeMaintenanceRecord,
    AxeOrchestratorStatus,
    AxeProcessObservation,
    AxeRunnerOccupancy,
    AxeStatusCollectionError,
    AxeStatusIssue,
    AxeStatusSnapshot,
)
from sase.feature_flags import override_flags
from sase.main.axe_handler import handle_axe_command
from sase.main.parser import create_parser
from tests.main.parser_help_helpers import ANSI_RE


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


def _issue(
    summary: str = "AXE needs attention.",
    *,
    command: str | None = "sase axe ensure",
    subject: str | None = None,
) -> AxeStatusIssue:
    return AxeStatusIssue(
        code="test_issue",
        severity="error",
        subject=subject,
        summary=summary,
        suggested_command=command,
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


def _plain_render(snapshot: AxeStatusSnapshot, *, width: int = 140) -> str:
    output = StringIO()
    console = Console(
        file=output,
        width=width,
        force_terminal=False,
        color_system=None,
    )
    status_render.render_axe_status_human(snapshot, console=console)
    return output.getvalue()


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


def test_json_is_exact_stable_plain_wire_contract() -> None:
    snapshot = replace(
        _snapshot(),
        state="down",
        health="unhealthy",
        summary="AXE should be running but is down.",
        exit_code=1,
        issues=(_issue(),),
    )
    first = StringIO()
    second = StringIO()

    with override_flags(axe_routine_job_contract=False):
        status_render.render_axe_status_json(snapshot, stream=first)
        status_render.render_axe_status_json(snapshot, stream=second)

    assert first.getvalue() == second.getvalue()
    assert json.loads(first.getvalue()) == snapshot.to_wire()
    assert ANSI_RE.search(first.getvalue()) is None
    assert first.getvalue().endswith("\n")
    human = _plain_render(snapshot)
    assert "DOWN" in human
    assert "UNHEALTHY" in human
    assert snapshot.issues[0].summary in human
    assert f'"exit_code": {snapshot.exit_code}' in first.getvalue()


def test_json_public_contract_renames_routines_and_jobs_under_flag() -> None:
    output = StringIO()

    with override_flags(axe_routine_job_contract=True):
        status_render.render_axe_status_json(_snapshot(), stream=output)

    payload = json.loads(output.getvalue())
    assert payload["schema_version"] == 2
    assert "routines" in payload
    assert "lumberjacks" not in payload
    assert payload["routines"][0]["routine_name"] == "hooks"
    assert payload["routines"][0]["configured_jobs"] == [
        "alpha_check",
        "beta_check",
    ]


def test_json_public_contract_preserves_names_paths_and_payload_values() -> None:
    output = StringIO()
    snapshot = replace(
        _snapshot(),
        state="error",
        health="error",
        exit_code=2,
        summary=(
            "AXE status collection failed: "
            "failed to read /tmp/lumberjacks/chop-watch.log"
        ),
        lumberjacks=(
            replace(
                _lumberjack(name="chop-watch"),
                configured_chops=("chop-test",),
            ),
        ),
        collection_error=AxeStatusCollectionError(
            code="read_failed",
            message="failed to read /tmp/lumberjacks/chop-watch.log",
        ),
    )

    with override_flags(axe_routine_job_contract=True):
        status_render.render_axe_status_json(snapshot, stream=output)

    payload = json.loads(output.getvalue())
    text = output.getvalue()
    assert payload["routines"][0]["name"] == "chop-watch"
    assert payload["routines"][0]["routine_name"] == "chop-watch"
    assert payload["routines"][0]["configured_jobs"] == ["chop-test"]
    assert payload["collection_error"]["message"] == (
        "failed to read /tmp/lumberjacks/chop-watch.log"
    )
    assert "/tmp/lumberjacks/chop-watch.log" in text
    assert "job-watch" not in text
    assert "job-test" not in text
    assert "/tmp/routines/job-watch.log" not in text


def test_human_attention_uses_public_routine_issue_templates_in_both_flag_states() -> (
    None
):
    snapshot = replace(
        _snapshot(),
        state="degraded",
        health="unhealthy",
        exit_code=1,
        lumberjacks=(
            replace(
                _lumberjack(name="chop-watch", state="stale_heartbeat"),
                heartbeat_age_seconds=500,
            ),
        ),
        issues=(
            AxeStatusIssue(
                code="lumberjack_stale_heartbeat",
                severity="warning",
                subject="chop-watch",
                summary=(
                    "Configured lumberjack `chop-watch` has a stale heartbeat "
                    "(500s; threshold 90s)."
                ),
                suggested_command="sase doctor --deep",
            ),
        ),
    )

    with override_flags(axe_routine_job_contract=False):
        legacy_flag_output = _plain_render(snapshot)
    with override_flags(axe_routine_job_contract=True):
        public_flag_output = _plain_render(snapshot)

    for output in (legacy_flag_output, public_flag_output):
        assert (
            "Configured routine `chop-watch` has a stale heartbeat "
            "(500s; threshold 90s)."
        ) in output
        assert "Configured lumberjack `chop-watch`" not in output


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


@pytest.mark.parametrize(
    ("state", "health", "has_attention"),
    [
        ("running", "healthy", False),
        ("maintenance", "healthy", False),
        ("stopped", "healthy", False),
        ("not_started", "healthy", False),
        ("down", "unhealthy", True),
        ("error", "error", True),
    ],
)
def test_human_render_covers_lifecycle_state_families(
    state: str,
    health: str,
    has_attention: bool,
) -> None:
    issues = (_issue(),) if state == "down" else ()
    collection_error = (
        AxeStatusCollectionError(code="config_read_failed", message="broken config")
        if state == "error"
        else None
    )
    maintenance = (
        AxeMaintenanceRecord(
            reason="upgrade",
            owner_pid=999,
            started_at="2026-07-23T11:55:00+00:00",
            age_seconds=300,
        )
        if state == "maintenance"
        else None
    )
    snapshot = replace(
        _snapshot(),
        state=state,  # type: ignore[arg-type]
        health=health,  # type: ignore[arg-type]
        summary=f"Rendered {state}.",
        exit_code=0 if health == "healthy" else (1 if health == "unhealthy" else 2),
        maintenance=maintenance,
        issues=issues,
        collection_error=collection_error,
    )

    output = _plain_render(snapshot)

    assert state.replace("_", " ").upper() in output
    assert health.upper() in output
    assert ("Attention" in output) is has_attention
    if maintenance is not None:
        assert "upgrade" in output
        assert "owner PID=999" in output
        assert "5m 00s ago" in output
    if collection_error is not None:
        assert "config_read_failed" in output
        assert "sase doctor --deep" in output


@pytest.mark.parametrize("variant", ["orchestrator", "lumberjack", "orphan"])
def test_degraded_runtime_variants_are_visible(variant: str) -> None:
    snapshot = replace(
        _snapshot(),
        state="degraded",
        health="unhealthy",
        summary="AXE runtime is degraded.",
        exit_code=1,
        issues=(_issue(f"{variant} degradation"),),
    )
    if variant == "orchestrator":
        snapshot = replace(snapshot, orchestrator=_orchestrator(coherent=False))
    elif variant == "lumberjack":
        snapshot = replace(
            snapshot,
            lumberjacks=(_lumberjack(state="stale_heartbeat"),),
        )
    else:
        snapshot = replace(
            snapshot,
            lumberjacks=(
                _lumberjack(name="live-orphan", state="orphaned", configured=False),
            ),
        )

    output = _plain_render(snapshot)

    assert "DEGRADED" in output
    assert f"{variant} degradation" in output
    if variant == "orchestrator":
        assert "coherence=incoherent" in output
        assert "live PIDs=123, 124" in output
    elif variant == "lumberjack":
        assert "stale heartbeat" in output
    else:
        assert "live-orphan" in output
        assert "orphaned" in output


def test_narrow_table_folds_without_dropping_lumberjack_contract_facts() -> None:
    snapshot = replace(
        _snapshot(),
        lumberjacks=(
            _lumberjack(name="zeta"),
            _lumberjack(name="alpha"),
        ),
    )

    output = _plain_render(snapshot, width=58)
    folded = " ".join(output.split())

    assert output.index("alpha") < output.index("zeta")
    for fact in (
        "state=",
        "configured=",
        "interval=",
        "stale",
        "threshold=",
        "PID=",
        "live=",
        "reported=",
        "heartbeat=",
        "cycles=",
        "errors=",
        "uptime=",
        "started=",
        "age=",
        "jobs=",
        "load=",
        "alpha_check",
        "beta_check",
    ):
        assert fact in folded
    assert "…" not in output


def test_attention_preserves_issue_order_and_deduplicates_next_steps() -> None:
    snapshot = replace(
        _snapshot(),
        state="degraded",
        health="unhealthy",
        exit_code=1,
        issues=(
            _issue("First issue", command="sase axe ensure"),
            _issue("Second issue", command="sase axe ensure"),
            _issue("Third issue", command="sase doctor --deep"),
        ),
    )

    output = _plain_render(snapshot)

    assert output.index("First issue") < output.index("Second issue")
    assert output.index("Second issue") < output.index("Third issue")
    assert output.count("$ sase axe ensure") == 1
    assert output.count("$ sase doctor --deep") == 1


def test_terminal_color_is_enabled_deliberately_and_plain_when_redirected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    colored_output = StringIO()
    colored_console = Console(
        file=colored_output,
        width=120,
        force_terminal=True,
        color_system="standard",
    )

    status_render.render_axe_status_human(snapshot, console=colored_console)

    assert ANSI_RE.search(colored_output.getvalue()) is not None

    monkeypatch.setenv("NO_COLOR", "1")
    plain_output = StringIO()
    redirected_console = Console(
        file=plain_output,
        width=120,
        force_terminal=False,
    )
    status_render.render_axe_status_human(snapshot, console=redirected_console)

    assert ANSI_RE.search(plain_output.getvalue()) is None
