"""Successor evidence must be attached to the gate that launched it."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_wire import AgentArtifactRecordWire, RunningMarkerWire
from sase.core.paths import sase_projects_dir
from sase.gate_turn.handoff import classify_gate_handoff, collect_successor_evidence
from tests.monitor._fixtures import record_from_disk

PROJECT = "successor-evidence"
SESSION = "8f"


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _member(
    timestamp: str,
    name: str,
    *,
    gate_kind: str | None = None,
    creator: str | None = None,
    running: bool = False,
    completed: bool = False,
) -> AgentArtifactRecordWire:
    artifacts_dir = (
        sase_projects_dir()
        / PROJECT
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    meta = {"agent_session": SESSION, "name": name}
    if gate_kind is not None:
        meta["gate_kind"] = gate_kind
    if creator is not None:
        meta["gate_creator_agent"] = creator
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if running:
        (artifacts_dir / "running.json").write_text("{}", encoding="utf-8")
    if completed:
        (artifacts_dir / "done.json").write_text("{}", encoding="utf-8")
    record = record_from_disk(artifacts_dir)
    return replace(record, running=RunningMarkerWire()) if running else record


def _evidence(
    gate: AgentArtifactRecordWire,
    records: tuple[AgentArtifactRecordWire, ...],
    *,
    expected_suffix: str | None = None,
    recorded_agent: str | None = None,
    gate_timestamp: str | None = None,
    gate_kind: str | None = None,
    exclude_agents: set[str] | None = None,
) -> dict[str, Any]:
    meta = gate.agent_meta
    assert meta is not None
    artifact_meta = json.loads(
        (Path(gate.artifact_dir) / "agent_meta.json").read_text(encoding="utf-8")
    )
    return collect_successor_evidence(
        project_name=PROJECT,
        agent_session=SESSION,
        expected_suffix=expected_suffix,
        recorded_agent=recorded_agent,
        gate_kind=gate_kind or artifact_meta.get("gate_kind"),
        gate_timestamp=gate_timestamp or gate.timestamp,
        exclude_agents=exclude_agents
        or {
            artifact_meta.get("gate_creator_agent") or "",
            meta.name or "",
        },
        agent_session_records=records,
    )


def test_suffixless_sudo_gate_does_not_adopt_its_completed_creator() -> None:
    creator = _member("20261017084700", "8f--code", completed=True)
    gate = _member(
        "20261017084800",
        "8f--gate-0",
        gate_kind="sudo",
        creator="8f--code",
    )
    plan_gate = _member("20261017084600", "8f--gate", gate_kind="plan")

    evidence = _evidence(gate, (plan_gate, creator, gate))

    assert evidence["expected_suffix"] == "--@"
    assert evidence["running"] is False
    assert evidence["completed"] is False
    assert evidence["ambiguous"] is False
    assert evidence["attached_agent"] is None
    decision = classify_gate_handoff(
        {
            "gate_id": "incident-gate",
            "gate_kind": "sudo",
            "gate_state": "answered",
            "gate_request_fingerprint": "sha256:incident",
        },
        mode="settle",
        already_settled=False,
        followup_requested=True,
        successor_evidence=evidence,
    )
    assert decision["launch_allowed"] is True


def test_suffixless_sudo_gate_attaches_a_post_gate_numbered_successor() -> None:
    gate = _member(
        "20261017084800",
        "8f--gate-0",
        gate_kind="sudo",
        creator="8f--code",
    )
    successor = _member("20261017084801", "8f--0", running=True)

    evidence = _evidence(gate, (gate, successor))

    assert evidence["attached_agent"] == "8f--0"
    assert evidence["running"] is True


@pytest.mark.parametrize("explicit_suffix", [True, False])
def test_plan_gate_keeps_its_code_successor_convention(
    explicit_suffix: bool,
) -> None:
    gate = _member("20261017084800", "8f--gate", gate_kind="plan")
    successor = _member("20261017084801", "8f--code", running=True)

    evidence = _evidence(
        gate,
        (gate, successor),
        expected_suffix="--code" if explicit_suffix else None,
    )

    assert evidence["expected_suffix"] == "--code"
    assert evidence["attached_agent"] == "8f--code"


def test_later_plan_gate_ignores_a_code_member_from_an_earlier_cycle() -> None:
    earlier = _member("20261017084801", "8f--code", completed=True)
    gate = _member("20261017084802", "8f--gate-1", gate_kind="plan")

    evidence = _evidence(
        gate,
        (earlier, gate),
        recorded_agent="8f--code",
    )

    assert evidence["running"] is False
    assert evidence["completed"] is False
    assert evidence["attached_agent"] is None
    assert evidence["launch_receipt"] == "8f--code"


def test_numbered_template_rejects_gate_and_monitor_suffixes() -> None:
    gate = _member("20261017084800", "8f--gate", gate_kind="sudo")
    gate_member = _member("20261017084801", "8f--gate-1", running=True)
    monitor = _member("20261017084802", "8f--mon", running=True)

    evidence = _evidence(gate, (gate, gate_member, monitor))

    assert evidence["running"] is False
    assert evidence["completed"] is False
    assert evidence["ambiguous"] is False
    assert evidence["attached_agent"] is None


def test_malformed_gate_timestamp_still_excludes_the_creator() -> None:
    creator = _member("20261017084700", "8f--code", completed=True)
    gate = _member(
        "20261017084800",
        "8f--gate",
        gate_kind="plan",
        creator="8f--code",
    )

    evidence = _evidence(
        gate,
        (creator, gate),
        expected_suffix="--code",
        gate_timestamp="malformed",
    )

    assert evidence["running"] is False
    assert evidence["completed"] is False
    assert evidence["attached_agent"] is None
