"""``sase agent wait -T/--target`` binding, clan errors, and JSON."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.agents.cli_wait import handle_agents_wait
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    WorkflowStateWire,
)
from sase.core.process_identity import process_identity_token
from tests._agent_names_fixtures import make_agent


def _patch_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def _running_agent(
    base: Path,
    project: str,
    suffix: str,
    name: str,
    **kwargs: object,
) -> Path:
    extra = dict(kwargs.pop("extra_meta", {}) or {})
    extra["process_identity"] = process_identity_token(os.getpid())
    return make_agent(
        base,
        project,
        suffix,
        name,
        pid=os.getpid(),
        extra_meta=extra,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _session_root(base: Path, timestamp: str, name: str, **kwargs: object) -> Path:
    return make_agent(
        base,
        "proj",
        timestamp,
        f"{name}--plan",
        workflow_name=name,
        agent_session=name,
        role_suffix="--plan",
        **kwargs,  # type: ignore[arg-type]
    )


def _snapshot(*records: AgentArtifactRecordWire) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/sase/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=list(records),
    )


def _disk_record(
    artifact_dir: Path,
    *,
    name: str,
    pid: int | None = None,
    outcome: str | None = None,
    agent_session: str | None = None,
    parent_timestamp: str | None = None,
    clan: str | None = None,
    clan_generation: str | None = None,
    workflow_name: str | None = None,
) -> AgentArtifactRecordWire:
    project_dir = artifact_dir.parents[2]
    return AgentArtifactRecordWire(
        project_name=project_dir.name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_dir.name}.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(artifact_dir),
        timestamp=artifact_dir.name,
        agent_meta=AgentMetaWire(
            name=name,
            pid=pid,
            process_identity=process_identity_token(pid) if pid is not None else None,
            agent_session=agent_session,
            workflow_name=agent_session or workflow_name,
            parent_timestamp=parent_timestamp,
            agent_clan=clan,
            agent_clan_generation=clan_generation,
        ),
        done=DoneMarkerWire(outcome=outcome) if outcome is not None else None,
        workflow_state=(
            WorkflowStateWire(workflow_name=workflow_name)
            if workflow_name is not None
            else None
        ),
        has_done_marker=outcome is not None,
    )


def _synthetic_record(
    timestamp: str,
    *,
    name: str,
    pid: int | None = None,
    outcome: str | None = None,
    clan: str | None = None,
    clan_generation: str | None = None,
    workflow_name: str | None = None,
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
            agent_session=None,
            workflow_name=workflow_name,
            agent_clan=clan,
            agent_clan_generation=clan_generation,
        ),
        done=DoneMarkerWire(outcome=outcome) if outcome is not None else None,
        workflow_state=(
            WorkflowStateWire(workflow_name=workflow_name)
            if workflow_name is not None
            else None
        ),
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
    target: str = "session",
    json_mode: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        names=names or [],
        all=all_,
        project=None,
        json=json_mode,
        quiet=False,
        wait_blocked=False,
        interval=None,
        timeout=None,
        target=target,
    )


def test_turn_target_pins_pending_gate_and_ignores_later_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    gate = _running_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "16h--gate",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--gate",
        parent_timestamp=root.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )
    plan_record = _disk_record(
        root, name="16h--plan", outcome="completed", agent_session="16h"
    )
    gate_live = _disk_record(
        gate,
        name="16h--gate",
        pid=os.getpid(),
        agent_session="16h",
        parent_timestamp=root.name,
    )
    gate_done = _disk_record(
        gate,
        name="16h--gate",
        outcome="completed",
        agent_session="16h",
        parent_timestamp=root.name,
    )
    code_live = _disk_record(
        gate.parent / "20260506010303",
        name="16h--code",
        pid=os.getpid(),
        agent_session="16h",
        parent_timestamp=root.name,
    )
    snapshots = _sequence(
        _snapshot(plan_record, gate_live),
        _snapshot(plan_record, gate_done, code_live),
    )

    rc = handle_agents_wait(
        _args(names=["16h"], target="turn", json_mode=True),
        snapshot_provider=lambda: next(snapshots),
        install_signal_handlers=False,
        sleep=lambda _seconds: None,
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["targets"]) == 1
    target = payload["targets"][0]
    assert target["turn_name"] == "16h--gate"
    assert target["name"] == "16h--gate"
    assert target["kind"] == "agent"
    assert target["artifacts_dir"] == str(gate)
    assert target["state"] == "succeeded"


def test_turn_target_json_reports_bound_turn_name_for_finished_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_home(monkeypatch, tmp_path)
    solo = _running_agent(tmp_path, "proj", "20260506010101", "solo")
    (solo / "done.json").write_text(json.dumps({"outcome": "completed"}))
    snapshot = _snapshot(
        _disk_record(solo, name="solo", outcome="completed"),
    )

    rc = handle_agents_wait(
        _args(names=["solo"], target="turn", json_mode=True),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
        sleep=lambda _seconds: None,
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["targets"][0]["turn_name"] == "solo"


def test_turn_target_clan_is_usage_error_with_core_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(
        _synthetic_record(
            "20260823120000",
            name="review.a",
            outcome="completed",
            clan="builders",
            clan_generation="g1",
        ),
        _synthetic_record(
            "20260823120001",
            name="review.b",
            pid=123,
            clan="builders",
            clan_generation="g1",
        ),
    )

    rc = handle_agents_wait(
        _args(names=["builders"], target="turn"),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "target=turn" in err
    assert "`builders`" in err
    assert "clan has no single turn" in err


def test_turn_target_workflow_is_usage_error_with_core_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = _snapshot(
        _synthetic_record(
            "20260823120000",
            name="step-1",
            pid=123,
            workflow_name="ship",
        )
    )

    rc = handle_agents_wait(
        _args(names=["ship"], target="turn"),
        snapshot_provider=lambda: snapshot,
        install_signal_handlers=False,
    )

    assert rc == 2
    err = capsys.readouterr().err
    assert "target=turn" in err
    assert "`ship`" in err
    assert "turn needs an existing agent" in err


def test_turn_target_cannot_combine_with_all(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = handle_agents_wait(
        _args(all_=True, target="turn"),
        snapshot_provider=lambda: _snapshot(),
        install_signal_handlers=False,
    )

    assert rc == 2
    assert "cannot be combined with -a/--all" in capsys.readouterr().err
