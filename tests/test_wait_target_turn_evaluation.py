"""Turn-scoped identity evaluation and v2 record persistence (wait_runtime)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.axe.run_agent_directive_metadata_preserved import (
    preserved_agent_metadata,
)
from sase.axe.run_agent_wait_deps import _forward_identity_deps
from sase.axe.run_agent_wait_markers import write_waiting_marker
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._gate_wait_dependency_helpers import _write_gate_done


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


def _session_member(
    base: Path,
    timestamp: str,
    session: str,
    role: str,
    parent: Path,
    **kwargs: object,
) -> Path:
    extra = dict(kwargs.pop("extra_meta", {}) or {})
    if role == "gate":
        extra.setdefault("agent_session_role", "gate")
        extra.setdefault("gate_id", "gate-1")
    return make_agent(
        base,
        "proj",
        timestamp,
        f"{session}--{role}",
        workflow_name=session,
        agent_session=session,
        role_suffix=f"--{role}",
        parent_timestamp=parent.name,
        extra_meta=extra,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


def _index(tmp_path: Path) -> WaitDependencyIndex:
    return build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )


def _turn_record(
    artifact_dir: Path,
    *,
    name: str,
    turn_name: str,
    requested: str | None = None,
) -> dict[str, Any]:
    return {
        "record_version": 2,
        "requested": requested or name,
        "name": name,
        "target": "turn",
        "target_explicit": True,
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "turn_name": turn_name,
    }


def _session_record(artifact_dir: Path, *, name: str) -> dict[str, Any]:
    return {
        "record_version": 2,
        "requested": name,
        "name": name,
        "target": "session",
        "target_explicit": True,
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
    }


def test_turn_record_releases_when_pinned_gate_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    gate = _session_member(tmp_path, "20260506010202", "16h", "gate", root)
    _write_gate_done(gate, gate_state="answered", followup_agent="16h--code")
    _session_member(tmp_path, "20260506010303", "16h", "code", gate)

    index = _index(tmp_path)
    record = _turn_record(gate, name="16h", turn_name="16h--gate")
    assert index.identity_status(record).resolved
    assert dependency_resolution_status(index, ["16h"], [record]).resolved
    assert not dependency_resolution_status(
        index, ["16h"], [_session_record(root, name="16h")]
    ).resolved


def test_failed_pinned_turn_not_released_by_later_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    gate = _session_member(
        tmp_path,
        "20260506010202",
        "16h",
        "gate",
        root,
        done=True,
        outcome="failed",
    )
    _session_member(
        tmp_path,
        "20260506010303",
        "16h",
        "code",
        gate,
        done=True,
        outcome="completed",
    )

    index = _index(tmp_path)
    record = _turn_record(gate, name="16h", turn_name="16h--gate")
    status = index.identity_status(record)
    assert not status.resolved
    assert not dependency_resolution_status(index, ["16h"], [record]).resolved


def test_turn_record_on_root_does_not_expand_to_later_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    _session_member(tmp_path, "20260506010202", "16h", "gate", root)

    index = _index(tmp_path)
    record = _turn_record(root, name="16h", turn_name="16h--plan")
    assert index.identity_status(record).resolved
    assert not index.identity_status(_session_record(root, name="16h")).resolved


def test_turn_member_dirs_include_only_pinned_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    gate = _session_member(tmp_path, "20260506010202", "16h", "gate", root)
    code = _session_member(tmp_path, "20260506010303", "16h", "code", gate)

    index = _index(tmp_path)
    record = _turn_record(gate, name="16h", turn_name="16h--gate")
    member_dirs = index.dependency_member_dirs(["16h"], [record])
    assert str(gate) in member_dirs
    assert str(root) not in member_dirs
    assert str(code) not in member_dirs

    session_dirs = index.dependency_member_dirs(
        ["16h"], [_session_record(root, name="16h")]
    )
    assert str(root) in session_dirs
    assert str(gate) in session_dirs
    assert str(code) in session_dirs


def test_waiting_json_round_trips_v2_keys(tmp_path: Path) -> None:
    record = _turn_record(
        tmp_path / "20260506010202",
        name="16h",
        turn_name="16h--gate",
    )
    waiter = make_waiting_agent(tmp_path, "16h", wait_for_artifacts=[record])
    loaded = json.loads((waiter / "waiting.json").read_text(encoding="utf-8"))
    persisted = loaded["wait_for_artifacts"][0]
    for key in (
        "record_version",
        "requested",
        "name",
        "target",
        "target_explicit",
        "turn_name",
        "artifact_dir",
        "timestamp",
        "project_name",
    ):
        assert persisted[key] == record[key]


def test_write_waiting_marker_keeps_v2_keys(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "waiter"
    artifacts_dir.mkdir()
    record = _turn_record(
        tmp_path / "20260506010202",
        name="16h",
        turn_name="16h--gate",
    )
    write_waiting_marker(
        str(artifacts_dir),
        {
            "waiting_for": ["16h"],
            "wait_for_artifacts": [record],
            "cl_name": "waiter-cl",
            "timestamp": "waiter",
        },
    )
    loaded = json.loads((artifacts_dir / "waiting.json").read_text(encoding="utf-8"))
    assert loaded["wait_for_artifacts"][0] == record


def test_forward_identity_deps_copies_v2_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "old" / "20260506010202"
    new = tmp_path / "new" / "20260506019999"
    new.mkdir(parents=True)
    record = _turn_record(old, name="16h", turn_name="16h--gate")
    monkeypatch.setattr(
        "sase.agent.auto_restart.forward.find_replacement_artifacts_dir",
        lambda _old: str(new),
    )
    mapped = _forward_identity_deps([record])
    assert mapped[0]["artifact_dir"] == str(new)
    assert mapped[0]["target"] == "turn"
    assert mapped[0]["turn_name"] == "16h--gate"
    assert mapped[0]["record_version"] == 2
    assert mapped[0]["target_explicit"] is True
    assert record["artifact_dir"] == str(old)


def test_preserved_metadata_keeps_v2_wait_records(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    record = _turn_record(
        tmp_path / "20260506010202",
        name="16h",
        turn_name="16h--gate",
    )
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"wait_for_artifacts": [record]}),
        encoding="utf-8",
    )
    preserved = preserved_agent_metadata(str(artifacts_dir))
    assert preserved["wait_for_artifacts"] == [record]
    preserved["wait_for_artifacts"][0]["turn_name"] = "mutated"
    assert record["turn_name"] == "16h--gate"


def test_running_pinned_turn_stays_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    gate = _session_member(tmp_path, "20260506010202", "16h", "gate", root)
    index = _index(tmp_path)
    record = _turn_record(gate, name="16h", turn_name="16h--gate")
    assert not index.identity_status(record).resolved
