"""Behavior tests for ``sase agent wait`` (the CLI, not the wait engine)."""

from __future__ import annotations

import argparse
import json
import os
import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.agents.cli_wait import _WaitSignalState, handle_agents_wait
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    PlanPathMarkerWire,
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
    family: str | None = None,
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
        ),
        done=DoneMarkerWire(outcome=outcome) if outcome is not None else None,
        plan_path=PlanPathMarkerWire(plan_path=plan_path) if plan_path else None,
        has_done_marker=outcome is not None,
    )


def _sequence(*snapshots: AgentArtifactScanWire) -> Iterator[AgentArtifactScanWire]:
    def gen() -> Iterator[AgentArtifactScanWire]:
        yield from snapshots
        while True:
            yield snapshots[-1]

    return gen()


def _args(
    *,
    names: list[str] | None = None,
    all_: bool = False,
    project: str | None = None,
    json_mode: bool = False,
    quiet: bool = False,
    wait_blocked: bool = False,
    interval: str | None = None,
    timeout: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        names=names or [],
        all=all_,
        project=project,
        json=json_mode,
        quiet=quiet,
        wait_blocked=wait_blocked,
        interval=interval,
        timeout=timeout,
    )


def _no_sleep(seconds: float) -> None:
    raise AssertionError(f"must not sleep, slept {seconds}")


def test_usage_error_when_no_names_and_not_all(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = handle_agents_wait(_args(), install_signal_handlers=False)

    assert rc == 2
    assert "provide at least one agent name" in capsys.readouterr().err


def test_usage_error_when_all_combined_with_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = handle_agents_wait(
        _args(names=["foo"], all_=True), install_signal_handlers=False
    )

    assert rc == 2
    assert "cannot be combined with NAME" in capsys.readouterr().err


def test_unknown_name_exits_usage_with_suggestions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="sase-s7.2", outcome="completed")
    )

    rc = handle_agents_wait(
        _args(names=["sase-s7.3"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "no agent wait target found for 'sase-s7.3'" in err
    assert "did you mean: sase-s7.2" in err


def test_tribe_reference_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _snapshot()

    rc = handle_agents_wait(
        _args(names=["@some-tribe"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
    )

    assert rc == 2
    assert "tribe" in capsys.readouterr().err


def test_all_with_zero_eligible_targets_exits_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot()

    rc = handle_agents_wait(
        _args(all_=True),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
    )

    assert rc == 0
    assert "nothing to wait for" in capsys.readouterr().out


def test_all_excludes_caller_and_its_family(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()
    (caller_dir / "agent_meta.json").write_text(
        json.dumps({"name": "0bd", "agent_family": "0bd"}), encoding="utf-8"
    )
    caller_record = _record("20260823120000", name="0bd", pid=os.getpid(), family="0bd")
    monitor_member = _record(
        "20260823120001", name="0bd--mon-1", pid=os.getpid(), family="0bd"
    )
    other_running = _record("20260823120002", name="good", pid=os.getpid())
    other_done = _record("20260823120002", name="good", outcome="completed")
    alive = _snapshot(caller_record, monitor_member, other_running)
    done = _snapshot(caller_record, monitor_member, other_done)
    snapshots = _sequence(alive, alive, done)

    rc = handle_agents_wait(
        _args(all_=True, json_mode=True),
        env={"SASE_ARTIFACTS_DIR": str(caller_dir)},
        snapshot_provider=lambda: next(snapshots),
        install_signal_handlers=False,
        sleep=lambda _seconds: None,
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [target["name"] for target in payload["targets"]] == ["good"]


def test_already_finished_target_settles_without_a_poll(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(_record("20260823120000", name="good", outcome="completed"))

    rc = handle_agents_wait(
        _args(names=["good"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 0
    assert "settled: 1 succeeded, 0 failed, 0 blocked" in capsys.readouterr().out


def test_exit_code_failed() -> None:
    snapshot = _snapshot(_record("20260823120000", name="bad", outcome="failed"))

    rc = handle_agents_wait(
        _args(names=["bad"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 1


def test_exit_code_blocked_by_default_needs_review() -> None:
    snapshot = _snapshot(
        _record("20260823120000", name="planner", plan_path="/tmp/plan.md")
    )

    rc = handle_agents_wait(
        _args(names=["planner"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 3


def test_wait_blocked_flag_continues_through_blocked_state() -> None:
    blocked = _snapshot(
        _record("20260823120000", name="planner", plan_path="/tmp/plan.md")
    )
    done = _snapshot(_record("20260823120000", name="planner", outcome="completed"))
    snapshots = _sequence(blocked, blocked, done)
    clock_values = iter([0.0, 0.0, 0.25, 0.25])

    rc = handle_agents_wait(
        _args(names=["planner"], wait_blocked=True, interval="0.25"),
        snapshot_provider=lambda: next(snapshots),
        install_signal_handlers=False,
        clock=lambda: next(clock_values),
        sleep=lambda _seconds: None,
    )

    assert rc == 0


def test_exit_code_timeout() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=os.getpid()))
    clock_values = iter([0.0, 0.0, 3.0])

    rc = handle_agents_wait(
        _args(names=["runner"], timeout="3s", interval="1s"),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        clock=lambda: next(clock_values),
        sleep=lambda _seconds: None,
    )

    assert rc == 4


def test_interrupted_by_sigint_exits_130() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=os.getpid()))
    state = _WaitSignalState()
    state.signum = signal.SIGINT

    rc = handle_agents_wait(
        _args(names=["runner"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        signal_state=state,
        sleep=_no_sleep,
    )

    assert rc == 130


def test_interrupted_by_sigterm_exits_143() -> None:
    snapshot = _snapshot(_record("20260823120000", name="runner", pid=os.getpid()))
    state = _WaitSignalState()
    state.signum = signal.SIGTERM

    rc = handle_agents_wait(
        _args(names=["runner"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        signal_state=state,
        sleep=_no_sleep,
    )

    assert rc == 143


def test_progress_goes_to_stderr_and_summary_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(_record("20260823120000", name="good", outcome="completed"))

    rc = handle_agents_wait(
        _args(names=["good"]),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert "waiting on 1 agent: good" in captured.err
    assert "GOOD" not in captured.err  # no spurious transition noise beyond the state
    assert captured.out.strip().startswith("settled:")
    assert "settled:" not in captured.err


def test_quiet_mode_suppresses_progress(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _snapshot(_record("20260823120000", name="good", outcome="completed"))

    rc = handle_agents_wait(
        _args(names=["good"], quiet=True),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip().startswith("settled:")


def test_json_envelope_schema(capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = _snapshot(_record("20260823120000", name="bad", outcome="failed"))

    rc = handle_agents_wait(
        _args(names=["bad"], json_mode=True),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=_no_sleep,
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["settled"] == "failed"
    assert payload["exit_code"] == 1
    assert payload["timed_out"] is False
    assert isinstance(payload["waited_seconds"], (int, float))
    assert len(payload["targets"]) == 1
    target = payload["targets"][0]
    assert target["name"] == "bad"
    assert target["kind"] == "agent"
    assert target["state"] == "failed"
    assert target["status"] == "FAILED"
    assert target["outcome"] == "failed"
    assert "duration_seconds" in target
    assert "artifacts_dir" in target
    assert "error" in target
    assert "blocked_reason" in target
