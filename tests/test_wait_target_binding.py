"""Wait-target binder table cells and current-turn selection (phase: wait_runtime)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.wait_target_binding import bind_explicit_wait_targets, bind_wait_target
from sase.axe.run_agent_directives_flow import resolve_wait_state
from sase.core.process_identity import process_identity_token
from sase.core.wait_dependency_resolution import WaitDependencyIndex
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent


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


def _directives(
    *names: str, wait_targets: dict[str, str] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        wait=list(names),
        wait_beads=[],
        wait_hoods=[],
        wait_for_epics_of=[],
        wait_targets=wait_targets,
    )


def _resolve(
    *names: str,
    wait_targets: dict[str, str] | None = None,
    waiter_artifact_dir: Path | None = None,
    preserved_metadata: dict[str, object] | None = None,
) -> object:
    return resolve_wait_state(
        _directives(*names, wait_targets=wait_targets),
        fork_reference_prompt="",
        batch_predecessor_binding=None,
        agent_session_attach_plan=None,
        wait_targets=wait_targets,
        waiter_artifact_dir=waiter_artifact_dir,
        preserved_metadata=preserved_metadata,
    )


def test_bare_name_session_omitted_writes_no_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    _running_agent(tmp_path, "proj", "20260506010101", "solo")

    binding = bind_wait_target("solo")
    assert binding.kind == "bare_agent"
    assert binding.target == "session"
    assert binding.target_explicit is False
    assert binding.scope == "session"
    assert binding.identity_record is None


def test_bare_name_explicit_session_writes_no_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    _running_agent(tmp_path, "proj", "20260506010101", "solo")

    binding = bind_wait_target("solo", requested_target="session")
    assert binding.target == "session"
    assert binding.target_explicit is True
    assert binding.identity_record is None


def test_exact_member_omitted_pins_that_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root = _session_root(
        tmp_path, "20260506010101", "lane", done=True, outcome="completed"
    )
    _session_member(tmp_path, "20260506010202", "lane", "gate", root)

    binding = bind_wait_target("lane--plan")
    assert binding.kind == "exact_member"
    assert binding.scope == "member"
    assert binding.target == "turn"
    assert binding.target_explicit is False
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(root)
    assert binding.identity_record["turn_name"] == "lane--plan"
    assert binding.identity_record["record_version"] == 2


def test_exact_member_explicit_session_pins_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root = _session_root(
        tmp_path, "20260506010101", "lane", done=True, outcome="completed"
    )
    gate = _running_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "lane--gate",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--gate",
        parent_timestamp=root.name,
        extra_meta={"agent_session_role": "gate", "gate_id": "gate-1"},
    )

    binding = bind_wait_target("lane--gate", requested_target="session")
    assert binding.kind == "exact_member"
    assert binding.scope == "session"
    assert binding.target_explicit is True
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(root)
    assert binding.identity_record["name"] == "lane"
    assert binding.identity_record["target"] == "session"
    assert "turn_name" not in binding.identity_record
    assert gate.exists()


def test_bare_name_turn_pins_pending_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    waiter = make_waiting_agent(tmp_path, "16h")

    binding = bind_wait_target(
        "16h",
        requested_target="turn",
        waiter_artifact_dir=waiter,
    )
    assert binding.kind == "bare_agent"
    assert binding.scope == "current_turn"
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(gate)
    assert binding.identity_record["turn_name"] == "16h--gate"
    assert binding.identity_record["name"] == "16h"
    assert binding.identity_record["target_explicit"] is True


def test_current_turn_after_all_members_finish_pins_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root = _session_root(
        tmp_path, "20260506010101", "16h", done=True, outcome="completed"
    )
    _session_member(
        tmp_path,
        "20260506010202",
        "16h",
        "gate",
        root,
        done=True,
        outcome="gated",
        extra_meta={"gate_state": "answered"},
    )
    code = _session_member(
        tmp_path,
        "20260506010303",
        "16h",
        "code",
        root,
        done=True,
        outcome="completed",
    )

    binding = bind_wait_target("16h", requested_target="turn")
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(code)
    assert binding.identity_record["turn_name"] == "16h--code"


def test_current_turn_excludes_waiter_and_parked_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    code = _session_member(tmp_path, "20260506010303", "16h", "code", root)
    (code / "waiting.json").write_text(
        json.dumps({"waiting_for": ["other"]}), encoding="utf-8"
    )

    binding = bind_wait_target(
        "16h",
        requested_target="turn",
        waiter_artifact_dir=code,
    )
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(gate)
    assert binding.identity_record["turn_name"] == "16h--gate"


def test_plain_agent_turn_is_session_of_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    solo = _running_agent(tmp_path, "proj", "20260506010101", "solo")

    binding = bind_wait_target("solo", requested_target="turn")
    assert binding.scope == "current_turn"
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(solo)
    assert binding.identity_record["turn_name"] == "solo"


def test_clan_turn_is_launch_error() -> None:
    with (
        patch(
            "sase.agent.wait_target_binding.find_agent_clan",
            return_value=MagicMock(),
        ),
        pytest.raises(RuntimeError, match="`builders`"),
    ):
        bind_wait_target("builders", requested_target="turn")


def test_tribe_turn_is_launch_error() -> None:
    with pytest.raises(RuntimeError, match="`@job`"):
        bind_wait_target("@job", requested_target="turn")


def test_unresolved_turn_is_launch_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="`missing`"):
        bind_wait_target("missing", requested_target="turn")


def test_proc_turn_writes_no_identity() -> None:
    with patch(
        "sase.agent.wait_target_binding.resolved_proc_id",
        return_value="proc-1",
    ):
        binding = bind_wait_target("myproc", requested_target="turn")
    assert binding.kind == "proc"
    assert binding.scope == "single"
    assert binding.identity_record is None


def test_bind_explicit_wait_targets_skips_session_bare_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    _running_agent(tmp_path, "proj", "20260506010101", "solo")
    assert bind_explicit_wait_targets({"solo": "session"}) == []


def test_resolve_wait_state_appends_turn_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    waiter = make_waiting_agent(tmp_path, "16h")

    state = _resolve(
        "16h",
        wait_targets={"16h": "turn"},
        waiter_artifact_dir=waiter,
    )
    assert len(state.wait_identity_deps) == 1
    record = state.wait_identity_deps[0]
    assert record["target"] == "turn"
    assert record["turn_name"] == "16h--gate"
    assert record["artifact_dir"] == str(gate)


def test_resolve_wait_state_reuses_preserved_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    waiter = make_waiting_agent(tmp_path, "16h")
    first = _resolve(
        "16h",
        wait_targets={"16h": "turn"},
        waiter_artifact_dir=waiter,
    )
    pinned = first.wait_identity_deps[0]
    assert pinned["artifact_dir"] == str(gate)

    _running_agent(
        tmp_path,
        "proj",
        "20260506010303",
        "16h--code",
        workflow_name="16h",
        agent_session="16h",
        role_suffix="--code",
        parent_timestamp=root.name,
    )
    rebound = bind_wait_target(
        "16h",
        requested_target="turn",
        waiter_artifact_dir=waiter,
    )
    assert rebound.identity_record is not None
    assert rebound.identity_record["turn_name"] == "16h--code"

    reused = _resolve(
        "16h",
        wait_targets={"16h": "turn"},
        waiter_artifact_dir=waiter,
        preserved_metadata={"wait_for_artifacts": [dict(pinned)]},
    )
    assert reused.wait_identity_deps == [pinned]


def test_index_can_be_injected_for_current_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_home(monkeypatch, tmp_path)
    root = _session_root(
        tmp_path, "20260506010101", "lane", done=True, outcome="completed"
    )
    gate = _session_member(tmp_path, "20260506010202", "lane", "gate", root)
    index = WaitDependencyIndex.empty()
    index.add_many(
        (
            artifact_dir,
            json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
            "proj",
        )
        for artifact_dir in (root, gate)
    )
    binding = bind_wait_target("lane", requested_target="turn", index=index)
    assert binding.identity_record is not None
    assert binding.identity_record["artifact_dir"] == str(gate)
