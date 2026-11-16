"""Pre/post-spawn hijack latch admission and recovery exceptions."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.hijack import ledger
from sase.agent.hijack._recovery_successor_common import (
    RECOVERY_LINEAGE_ENV,
    encode_recovery_lineage,
)
from sase.agent.hijack.spawn_guard import (
    HijackLatchedError,
    SpawnLatchGuard,
    latch_guard_from_predecessor,
    refuse_if_latched,
    spawn_admission,
)
from sase.agent.launcher import spawn_agent_subprocess
from sase.running_field import ClaimResult, WorkspaceClaimError


@pytest.fixture
def latch_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_hijack_ledger_root", lambda: tmp_path / "ledger")
    monkeypatch.setattr(ledger, "agent_hijack_wire_schema_version", lambda: 1)
    return tmp_path / "ledger"


def _write_meta(
    artifacts: Path, *, name: str = "agent.1", session: str = "session-1"
) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": name,
                "agent_session": session,
                "project_file": "/tmp/sample.sase",
                "pid": 42,
                "process_identity": "boot:123",
            }
        ),
        encoding="utf-8",
    )


def _write_latch(
    artifacts: Path,
    *,
    hijack_id: str = "hijack-1",
    state: str = "latched",
    name: str = "agent.1",
    session: str = "session-1",
    latched_at: int | None = 1,
) -> tuple[str, SpawnLatchGuard]:
    _write_meta(artifacts, name=name, session=session)
    target_key = ledger.target_key_for("/tmp/sample.sase", session)
    record = ledger.new_requested_record(
        hijack_id=hijack_id,
        agent_name=name,
        artifacts_dir=str(artifacts),
        pid=42,
        process_identity_token="boot:123",
        project_file="/tmp/sample.sase",
        workspace_num=4,
        workspace_dir="/tmp/workspace-4",
        session=session,
        target_key=target_key,
        scope="llm",
    )
    record["state"] = state
    record["latched_at"] = latched_at
    record["owner_pid"] = 42
    record["owner_identity"] = "boot:123"
    ledger.create_record(record)
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent=session,
        artifacts_dir=str(artifacts),
        member=name,
    )
    assert guard is not None
    return target_key, guard


def test_hijack_latched_error_is_not_a_runtime_error() -> None:
    error = HijackLatchedError("latched", hijack_id="h1", verdict="pending")
    assert not isinstance(error, RuntimeError)
    assert not isinstance(error, WorkspaceClaimError)
    assert error.hijack_id == "h1"
    assert error.verdict == "pending"


def test_refuse_if_latched_before_spawn_keeps_predecessor_record(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    target_key, guard = _write_latch(artifacts)
    with pytest.raises(HijackLatchedError, match="pending") as excinfo:
        refuse_if_latched(guard, boundary="spawn")
    assert excinfo.value.target_key == target_key
    assert ledger.find_active_record_by_target_key(target_key) is not None


def test_refuse_if_latched_ignores_unrelated_artifacts(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    _write_latch(tmp_path / "latched")
    other = tmp_path / "other"
    _write_meta(other, name="agent.2")
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(other),
        member="agent.2",
    )
    assert guard is not None
    refuse_if_latched(guard, boundary="spawn")


def test_ordinary_launch_without_predecessor_skips_latch_check(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    _write_latch(tmp_path / "latched")
    assert latch_guard_from_predecessor(artifacts_dir="") is None
    assert latch_guard_from_predecessor(artifacts_dir=None) is None


@pytest.mark.parametrize("state", ["stopping", "held"])
def test_authorized_recovery_successor_is_admitted_after_apply(
    latch_store: Path, tmp_path: Path, state: str
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    _write_latch(artifacts, state=state)
    extra_env = {
        RECOVERY_LINEAGE_ENV: encode_recovery_lineage(
            {
                "hijack_id": "hijack-1",
                "from_rung": "x",
                "to_rung": "continue",
                "predecessor": "agent.1",
            }
        )
    }
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
        extra_env=extra_env,
    )
    assert guard is not None
    refuse_if_latched(guard, boundary="spawn")


def test_authorized_recovery_still_refuses_a_pending_latch(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    _write_latch(artifacts, state="latched")
    extra_env = {
        RECOVERY_LINEAGE_ENV: encode_recovery_lineage(
            {
                "hijack_id": "hijack-1",
                "from_rung": "x",
                "to_rung": "continue",
                "predecessor": "agent.1",
            }
        )
    }
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
        extra_env=extra_env,
    )
    assert guard is not None
    with pytest.raises(HijackLatchedError, match="pending"):
        refuse_if_latched(guard, boundary="spawn")


def test_mismatched_recovery_id_is_refused_after_apply(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    _write_latch(artifacts, state="held")
    extra_env = {
        RECOVERY_LINEAGE_ENV: encode_recovery_lineage(
            {
                "hijack_id": "other-hijack",
                "from_rung": "x",
                "to_rung": "continue",
                "predecessor": "agent.1",
            }
        )
    }
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
        extra_env=extra_env,
    )
    assert guard is not None
    with pytest.raises(HijackLatchedError, match="applied"):
        refuse_if_latched(guard, boundary="spawn")


def test_cancel_winner_allows_ordinary_successor(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    _target_key, guard = _write_latch(artifacts)
    ledger.hijack_record_path("hijack-1").unlink()
    refuse_if_latched(guard, boundary="spawn")


def _spawn_guarded_agent(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_spawn: MagicMock,
    latch_guard: SpawnLatchGuard | None,
    extra_env: dict[str, str] | None = None,
) -> None:
    output_path = tmp_path / "proj_ace-run-260101_120000.txt"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir(exist_ok=True)
    tmp_dir = tmp_path / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def fake_managed_tmpdir(*parts: str) -> str:
        managed = tmp_dir.joinpath(*parts)
        managed.mkdir(parents=True, exist_ok=True)
        return str(managed)

    monkeypatch.setattr("sase.core.paths.get_sase_managed_tmpdir", fake_managed_tmpdir)
    monkeypatch.setattr("sase.core.paths.sharded_path", lambda *_args: str(output_path))
    monkeypatch.setattr("sase.config.require_agent_owner_identity", lambda: None)
    spawn_agent_subprocess(
        cl_name="proj",
        project_file="/tmp/projects/proj/proj.sase",
        workspace_dir=str(workspace_dir),
        workspace_num=3,
        workflow_name="ace(run)-260101_120000",
        prompt="do work",
        timestamp="260101_120000",
        project_name="proj",
        extra_env=extra_env,
        latch_guard=latch_guard,
    )


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_pre_spawn_latch_does_not_create_a_child(
    mock_spawn: MagicMock,
    _mock_claim: MagicMock,
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    _target_key, guard = _write_latch(tmp_path / "pred")
    with pytest.raises(HijackLatchedError, match="pending"):
        _spawn_guarded_agent(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_spawn=mock_spawn,
            latch_guard=guard,
        )
    mock_spawn.assert_not_called()
    _mock_claim.assert_not_called()


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_latch_between_spawn_and_callback_refuses_without_claiming(
    mock_spawn: MagicMock,
    mock_claim: MagicMock,
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    artifacts = tmp_path / "pred"
    _write_meta(artifacts)
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
    )
    claim_called = False

    def fake_spawn(
        _prepared: object,
        *,
        env: dict[str, str],
        claim_callback: Callable[[int], bool] | None = None,
    ) -> int:
        del env
        _write_latch(artifacts)
        assert claim_callback is not None
        claim_callback(99)
        return 99

    def tracking_claim(*_args: object, **_kwargs: object) -> ClaimResult:
        nonlocal claim_called
        claim_called = True
        return ClaimResult(success=True)

    mock_spawn.side_effect = fake_spawn
    mock_claim.side_effect = tracking_claim
    with pytest.raises(HijackLatchedError, match="pending"):
        _spawn_guarded_agent(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            mock_spawn=mock_spawn,
            latch_guard=guard,
        )
    mock_spawn.assert_called_once()
    assert claim_called is False
    assert ledger.find_active_record_by_target_key(guard.target_key) is not None


@patch("sase.running_field.claim_workspace", return_value=ClaimResult(success=True))
@patch("sase.core.agent_launch_facade.spawn_prepared_agent_process")
def test_ordinary_spawn_without_predecessor_still_launches(
    mock_spawn: MagicMock,
    _mock_claim: MagicMock,
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del latch_store
    _write_latch(tmp_path / "unrelated")
    mock_spawn.return_value = 4321
    _spawn_guarded_agent(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        mock_spawn=mock_spawn,
        latch_guard=None,
    )
    mock_spawn.assert_called_once()


def test_spawn_admission_holds_target_index_before_patch_lock(
    latch_store: Path, tmp_path: Path
) -> None:
    del latch_store
    from sase.agent.hijack.locks import _state

    artifacts = tmp_path / "pred"
    _write_meta(artifacts)
    guard = latch_guard_from_predecessor(
        project_file="/tmp/sample.sase",
        session_or_agent="session-1",
        artifacts_dir=str(artifacts),
        member="agent.1",
    )
    assert guard is not None
    _state.tracing = True
    _state.held = []
    _state.events = []
    try:
        with spawn_admission(guard, boundary="spawn_callback"):
            assert tuple(getattr(_state, "held", ())) == (
                "target_index",
                "patch_lock",
            )
        events = list(getattr(_state, "events", []))
    finally:
        _state.tracing = False
        _state.held = []
        _state.events = []
    names = [name for _action, name in events]
    assert names[:2] == ["target_index", "patch_lock"]
    assert ("release", "patch_lock") in events
    assert ("release", "target_index") in events


def test_detached_successor_delivery_holds_on_latched_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.staged_handoff import (
        acquire_adoption_lock,
        successor_prompt_digest,
        write_staged_successor_locked,
        write_successor_prompt,
    )
    from sase.axe.run_agent_successor import deliver_staged_successor_detached

    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "agent", "agent_session": "session-1"}),
        encoding="utf-8",
    )
    destination = tmp_path / "successor"
    destination.mkdir()
    (destination / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent--1",
                "staged_handoff_id": "stage-1",
                "staged_successor_launch_id": "stage-1:20261031010101",
            }
        ),
        encoding="utf-8",
    )
    prompt = "finish this work"
    prompt_ref = write_successor_prompt(origin, prompt)
    launch_prompt_ref = write_successor_prompt(
        origin, prompt, filename="staged_successor_launch_prompt.md"
    )
    project_file = tmp_path / "project.sase"
    project_file.write_text(
        "RUNNING:\n\nNAME: project\nSTATUS: Ready\n", encoding="utf-8"
    )
    successor = {
        "agent_name": "agent--1",
        "role_suffix": "--1",
        "artifacts_dir": str(destination),
        "artifacts_timestamp": "20261031_010101",
        "launch_timestamp": "20261031010101",
        "launch_identity": "stage-1:20261031010101",
        "prompt_ref": str(prompt_ref),
        "launch_prompt_ref": str(launch_prompt_ref),
        "prompt_digest": successor_prompt_digest(prompt),
        "launch_prompt_digest": successor_prompt_digest(prompt),
        "project_name": "sase",
        "project_file": str(project_file),
        "origin_artifacts_timestamp": "20261028_120000",
        "cl_name": "test-cl",
        "workspace_dir": str(tmp_path),
        "workspace_num": 1,
        "is_home_mode": False,
        "relationships": {
            "staged_handoff_id": "stage-1",
            "staged_successor_launch_id": "stage-1:20261031010101",
        },
        "continuation_refs": {},
        "loop_state": {},
        "attach_plan": None,
    }
    record = {
        "schema_version": 1,
        "staged_id": "stage-1",
        "kind": "pipe",
        "origin_artifacts_dir": str(origin),
        "delivery_state": "created",
        "successor": successor,
    }
    with acquire_adoption_lock(origin):
        write_staged_successor_locked(record, artifacts_dir=origin)

    def raise_latched(*_args: Any, **_kwargs: Any) -> None:
        raise HijackLatchedError(
            "hijack latch hijack-1 is pending; successor launch refused",
            hijack_id="hijack-1",
            verdict="pending",
        )

    monkeypatch.setattr("sase.agent.detached_child.spawn_detached_child", raise_latched)
    result = deliver_staged_successor_detached(str(origin), "stage-1")
    assert result.state == "held"
    assert "uncertain" not in (result.reason or "")
    assert "hijack latch hijack-1 is pending" in (result.reason or "")
