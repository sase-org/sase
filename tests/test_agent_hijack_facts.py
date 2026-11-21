"""Session occupant resolution for Agent Hijack facts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack.facts import _build_hijack_facts, resolve_and_decide
from sase.agent.names import AgentSession, AgentSessionMember, NamedAgent
from sase.agent.status_buckets import RUNNING_DISPLAY_ALIAS_STATUSES
from sase.running_field import WorkspaceClaim
from tests._running_field_helpers import create_project_file_with_running


def test_screenshot_session_name_resolves_to_claim_holding_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container name resolves to the monitor that owns the workspace claim."""
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                4,
                "ace(run)-20261115_164100",
                "fixture",
                pid=424244,
                artifacts_timestamp="20261115164108",
            )
        ],
    )
    specs = (
        (
            "tailnet-t.10--plan",
            "20261115164000",
            {"name": "tailnet-t.10--plan", "agent_session_role": "root"},
            "succeeded",
            None,
        ),
        (
            "tailnet-t.10--5",
            "20261115164054",
            {
                "name": "tailnet-t.10--5",
                "agent_session_role": "agent",
                "lifecycle_phase": "handoff",
                "finalizer_status": {"phase": "executing"},
                "runner_capabilities": ["hijack"],
                "llm_provider": "fakey",
                "model": "fakey-large",
                "pid": 424245,
                "agent_session": "tailnet-t.10",
            },
            None,
            "20261115164000",
        ),
        (
            "tailnet-t.10--mon-3",
            "20261115164108",
            {
                "name": "tailnet-t.10--mon-3",
                "agent_session": "tailnet-t.10",
                "agent_session_role": "monitor",
                "turn_kind": "monitor",
                "monitor_id": "mon-3",
                "monitor_state": "running",
                "runner_capabilities": ["hijack"],
                "pid": 424243,
            },
            None,
            "20261115164054",
        ),
    )
    members: list[AgentSessionMember] = []
    paths: dict[str, Path] = {}
    for name, timestamp, meta, outcome, parent_timestamp in specs:
        artifacts = tmp_path / timestamp
        artifacts.mkdir()
        (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        paths[name] = artifacts
        members.append(
            AgentSessionMember(
                name=name,
                artifacts_dir=artifacts,
                timestamp=timestamp,
                outcome=outcome,
                parent_timestamp=parent_timestamp,
            )
        )
    session = AgentSession(
        base_name="tailnet-t.10",
        root=members[0],
        members=tuple(members),
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session",
        lambda name: session if name == session.base_name else None,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        lambda path: (
            (session, members[0]) if Path(path) == paths[members[0].name] else None
        ),
    )
    monkeypatch.setattr("sase.agent.names.find_agent_clan", lambda _name: None)

    def project_fields(agent: Any) -> tuple[Path, str, str, str, bool]:
        artifacts = Path(agent.artifacts_dir)
        return artifacts, "proj", project_file, artifacts.name, False

    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", project_fields)
    root_agent = NamedAgent(
        name=members[0].name,
        artifacts_dir=str(paths[members[0].name]),
        is_done=True,
        outcome="succeeded",
    )
    rows = [
        SimpleNamespace(
            name=name,
            artifacts_dir=str(paths[name]),
            status="RUNNING",
            pid=meta.get("pid", 424244),
            agent_session="tailnet-t.10",
            monitor_state=meta.get("monitor_state"),
        )
        for name, _timestamp, meta, outcome, _parent in specs[1:]
    ]
    checked_pids: list[int | None] = []

    def process_alive(meta: dict[str, Any], _path: Path) -> bool:
        checked_pids.append(meta.get("pid"))
        return True

    deps = StopDeps(
        find_agent=lambda name: root_agent if name == "tailnet-t.10" else None,
        list_running=lambda: rows,
        process_alive=process_alive,
    )

    subject, decision = resolve_and_decide("tailnet-t.10", deps=deps)
    facts = _build_hijack_facts(subject)

    assert subject.is_session_container is True
    assert subject.occupant_name == "tailnet-t.10--mon-3"
    assert subject.target is not None
    assert subject.target.name == "tailnet-t.10--mon-3"
    assert "holds the workspace claim" in subject.occupant_reason
    assert facts["occupying_kind"] == "monitor"
    assert facts["workspace_num"] == 4
    assert facts["live_member_count"] == 2
    assert facts["monitor_followup_pending"] is False
    assert 424244 in checked_pids
    assert decision["mode"] == "immediate"
    assert decision["adapter"] == "monitor"
    assert decision["code"] is None


def test_stale_live_row_is_not_an_occupying_member() -> None:
    from sase.agent.hijack._facts_resolve import _status

    row = SimpleNamespace(status="RUNNING")

    assert _status(row, process_alive=False) == "LOST"


@pytest.mark.parametrize(
    ("row", "process_alive", "expected"),
    [
        *(
            (SimpleNamespace(status=label), True, "RUNNING")
            for label in sorted(RUNNING_DISPLAY_ALIAS_STATUSES)
        ),
        *(
            (SimpleNamespace(status=label), False, label)
            for label in sorted(RUNNING_DISPLAY_ALIAS_STATUSES)
        ),
        (SimpleNamespace(status="RUNNING"), False, "LOST"),
        (SimpleNamespace(status="DONE"), True, "DONE"),
        (None, True, "RUNNING"),
    ],
)
def test_status_normalizes_running_display_aliases(
    row: Any, process_alive: bool, expected: str
) -> None:
    from sase.agent.hijack._facts_resolve import _status

    assert _status(row, process_alive=process_alive) == expected


def _write_pending_delivery(artifacts: Path, *, disposition: str = "pending") -> None:
    from sase.monitor.delivery import (
        new_delivery_record,
        persist_delivery_record,
        transition_delivery,
    )

    key = {
        "monitor_id": "mon-3",
        "result_id": "result-1",
        "branch": "completed",
    }
    record = new_delivery_record(key, selected_action="continue")
    if disposition == "pending":
        persist_delivery_record(artifacts, record)
        return
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    if disposition == "reserved":
        persist_delivery_record(artifacts, reserved)
        return
    current = transition_delivery(reserved, "dispatching")
    if disposition == "dispatching":
        persist_delivery_record(artifacts, current)
        return
    current = transition_delivery(current, "acknowledged", acknowledged_by="acme--1")
    if disposition == "acknowledged":
        persist_delivery_record(artifacts, current)
        return
    persist_delivery_record(artifacts, transition_delivery(current, "settled"))


def _pending_monitor_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    meta_extra: dict[str, Any] | None = None,
    write_done: bool = True,
    process_alive: bool = False,
    row_status: str = "DONE",
) -> tuple[Any, dict[str, Any]]:
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(
                4,
                "20261115164108",
                "fixture",
                pid=424244,
                artifacts_timestamp="20261115164108",
            )
        ],
    )
    artifacts = tmp_path / "20261115164108"
    artifacts.mkdir(exist_ok=True)
    meta = {
        "name": "tailnet-t.10--mon-3",
        "agent_session": "tailnet-t.10",
        "agent_session_role": "monitor",
        "turn_kind": "monitor",
        "monitor_id": "mon-3",
        "monitor_state": "completed",
        "pid": 424243,
    }
    if meta_extra:
        meta.update(meta_extra)
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if write_done:
        (artifacts / "done.json").write_text(
            json.dumps({"outcome": "succeeded"}), encoding="utf-8"
        )
    member = AgentSessionMember(
        name="tailnet-t.10--mon-3",
        artifacts_dir=artifacts,
        timestamp="20261115164108",
        outcome="succeeded" if write_done else None,
        parent_timestamp=None,
    )
    session = AgentSession(
        base_name="tailnet-t.10",
        root=member,
        members=(member,),
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session",
        lambda name: session if name == session.base_name else None,
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        lambda path: (session, member) if Path(path) == artifacts else None,
    )
    monkeypatch.setattr("sase.agent.names.find_agent_clan", lambda _name: None)

    def project_fields(agent: Any) -> tuple[Path, str, str, str, bool]:
        return Path(agent.artifacts_dir), "proj", project_file, artifacts.name, False

    monkeypatch.setattr("sase.agent.running.named_agent_project_fields", project_fields)
    row = SimpleNamespace(
        name=member.name,
        artifacts_dir=str(artifacts),
        status=row_status,
        pid=424243,
        agent_session="tailnet-t.10",
        monitor_state=meta.get("monitor_state"),
    )
    deps = StopDeps(
        find_agent=lambda name: (
            NamedAgent(
                name=member.name,
                artifacts_dir=str(artifacts),
                is_done=write_done,
                outcome="succeeded" if write_done else None,
            )
            if name in {member.name, session.base_name}
            else None
        ),
        list_running=lambda: (
            [row] if row_status in {"STARTING", "RUNNING", "RETRYING"} else []
        ),
        process_alive=lambda _meta, _path: process_alive,
    )
    return resolve_and_decide("tailnet-t.10", deps=deps)


def test_pending_delivery_keeps_the_monitor_as_occupant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261115164108"
    artifacts.mkdir()
    _write_pending_delivery(artifacts, disposition="pending")
    subject, decision = _pending_monitor_session(tmp_path, monkeypatch)
    facts = _build_hijack_facts(subject)

    assert subject.occupant_name == "tailnet-t.10--mon-3"
    assert facts["occupying_kind"] == "monitor"
    assert facts["monitor_followup_pending"] is True
    assert facts["done_outcome"] == "succeeded"
    assert decision["mode"] == "latched"
    assert decision["boundary"] == "monitor"
    assert decision["code"] == "monitor_followup_pending"
    assert decision["adapter"] is None


def test_reserved_delivery_is_pending_and_acknowledged_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261115164108"
    artifacts.mkdir()
    _write_pending_delivery(artifacts, disposition="reserved")
    subject, decision = _pending_monitor_session(tmp_path, monkeypatch)
    assert _build_hijack_facts(subject)["monitor_followup_pending"] is True
    assert decision["mode"] == "latched"

    _write_pending_delivery(artifacts, disposition="acknowledged")
    subject, decision = _pending_monitor_session(tmp_path, monkeypatch)
    facts = _build_hijack_facts(subject)
    assert facts["monitor_followup_pending"] is False
    assert decision["mode"] == "refused"
    assert decision["code"] in {"already_completed", "ineligible_status", "not_found"}


def test_mere_monitor_next_action_is_not_pending_followup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, decision = _pending_monitor_session(
        tmp_path,
        monkeypatch,
        meta_extra={"monitor_next_action": "fix the failure"},
    )
    facts = _build_hijack_facts(subject)
    assert facts["monitor_followup_pending"] is False
    assert decision["mode"] == "refused"


def test_frozen_continue_policy_marks_settled_command_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, decision = _pending_monitor_session(
        tmp_path,
        monkeypatch,
        meta_extra={
            "continuation_frozen_policy": {
                "branches": {
                    "completed": {
                        "action": "continue",
                        "next_action": "fix the failure",
                    }
                }
            }
        },
    )
    facts = _build_hijack_facts(subject)
    assert facts["monitor_followup_pending"] is True
    assert decision["mode"] == "latched"
    assert decision["boundary"] == "monitor"


def test_terminal_followup_outcome_is_not_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject, decision = _pending_monitor_session(
        tmp_path,
        monkeypatch,
        meta_extra={
            "monitor_followup_outcome": "launched",
            "continuation_frozen_policy": {
                "branches": {
                    "completed": {
                        "action": "continue",
                        "next_action": "fix the failure",
                    }
                }
            },
        },
    )
    facts = _build_hijack_facts(subject)
    assert facts["monitor_followup_pending"] is False
    assert decision["mode"] == "refused"


def test_monitor_followup_pending_helper_uses_delivery_not_next_action(
    tmp_path: Path,
) -> None:
    from sase.agent.hijack._facts_resolve import _monitor_followup_pending

    artifacts = tmp_path / "mon"
    artifacts.mkdir()
    meta = {
        "monitor_next_action": "continue from here",
        "monitor_state": "completed",
    }
    assert (
        _monitor_followup_pending(
            str(artifacts),
            meta,
            occupying_kind="monitor",
            monitor_state="completed",
            done_outcome="succeeded",
        )
        is False
    )
    _write_pending_delivery(artifacts, disposition="pending")
    assert (
        _monitor_followup_pending(
            str(artifacts),
            meta,
            occupying_kind="monitor",
            monitor_state="completed",
            done_outcome="succeeded",
        )
        is True
    )
    assert (
        _monitor_followup_pending(
            str(artifacts),
            meta,
            occupying_kind="llm",
            monitor_state="completed",
            done_outcome="succeeded",
        )
        is False
    )


def test_named_lookup_unavailability_is_a_hijack_refusal() -> None:
    from sase.agent.names._lookup_named import AgentNamedLookupUnavailable

    def unavailable(_name: str) -> None:
        raise AgentNamedLookupUnavailable(
            availability="missing",
            source="fallback",
            diagnostic="fallback budget exhausted",
            truncated=True,
        )

    subject, decision = resolve_and_decide(
        "uncertain-agent",
        deps=StopDeps(find_agent=unavailable),
    )

    assert subject.target is None
    assert subject.lookup_error is not None
    assert decision["mode"] == "refused"
    assert decision["code"] == "lookup_unavailable"
    assert (
        decision["next_action"] == "retry after the agent artifact index is available"
    )


def test_session_and_clan_seams_skip_archive_lookups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AgentSession(
        base_name="seam.1",
        root=None,
        members=(),
    )

    def _raise(label: str) -> None:
        raise AssertionError(f"archive lookup {label}")

    monkeypatch.setattr(
        "sase.agent.names.find_named_agent",
        lambda *_a, **_k: _raise("agent"),
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session",
        lambda *_a, **_k: _raise("session"),
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_session_by_member_artifact_dir",
        lambda *_a, **_k: _raise("session-dir"),
    )
    monkeypatch.setattr(
        "sase.agent.names.find_agent_clan",
        lambda *_a, **_k: _raise("clan"),
    )

    deps = StopDeps(
        find_agent=lambda _name: None,
        list_running=lambda: [],
        find_session=lambda name: session if name == "seam.1" else None,
        find_session_by_member_artifact_dir=lambda _path: None,
        find_clan=lambda name: SimpleNamespace(name=name) if name == "wave-1" else None,
    )
    subject, decision = resolve_and_decide("wave-1", deps=deps)
    assert subject.is_clan_container is True
    assert decision["mode"] == "redirect"
