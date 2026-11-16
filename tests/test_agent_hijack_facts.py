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
    assert 424244 in checked_pids
    assert decision["mode"] == "refused"
    assert decision["code"] == "monitor_turn"


def test_stale_live_row_is_not_an_occupying_member() -> None:
    from sase.agent.hijack._facts_resolve import _status

    row = SimpleNamespace(status="RUNNING")

    assert _status(row, process_alive=False) == "LOST"


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
