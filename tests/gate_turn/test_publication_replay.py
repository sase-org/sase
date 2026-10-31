"""Request-id replay finishes missing gate publication without duplicating."""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from sase.gate_turn import transaction as transaction_module
from sase.gate_turn.member import create_gate_turn_member
from sase.gate_turn.models import GateTurnError
from sase.gate_turn.publisher import publish_staged_gate
from sase.gate_turn.staged_contract import prepare_staged_gate
from sase.gate_turn.start_claim import GateClaimMove
from sase.gate_turn.store import read_gate_turn_marker
from sase.gate_turn.transaction import (
    _spec_from_request,
    publish_gate_turn,
)
from sase.notification_gates.durability import atomic_write_json, read_json_object
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from sase.running_field import ClaimResult
from tests._notification_gates_fixtures import custom_gate_spec
from tests.gate_turn.test_staged_contract import _creator, _write_sources
from tests.gate_turn.test_transaction_gate_intent import _creation_result, _record

FROZEN_MANUAL = {
    "decision": {"profile": "manual", "outcome": "ask"},
    "policy_block": {"profile": "manual"},
    "auto_execute": False,
}


def _shell_block(workspace: str = "inherit") -> dict[str, Any]:
    return {
        "pending_status": "GATE",
        "settled_status": "GATED",
        "workspace": workspace,
        "next": {"prompt": "continue", "fork": "session", "output": ["results"]},
        "suffix": "--gate-replay",
    }


def _custom_spec(request_id: str, *, workspace: str = "inherit") -> dict[str, Any]:
    spec = custom_gate_spec(request_id=request_id)
    spec["shell"] = _shell_block(workspace)
    return spec


def _kind_spec(kind: str, request_id: str, artifacts_dir: str) -> dict[str, Any]:
    if kind == "custom":
        return _custom_spec(request_id)
    if kind == "sudo":
        from sase.sudo.gate import build_sudo_gate_request
        from tests._sudo_acceptance_helpers import _request

        return build_sudo_gate_request(_request(), request_id=request_id)
    if kind in {"launch", "run"}:
        from sase.agent.launch_request_gate import launch_gate_spec

        spec = launch_gate_spec(
            {
                "request_id": request_id,
                "dispatch": {"prompt": "do the work", "cwd": "/tmp"},
                "requester": {"agent": "agent"},
            },
            preview="# Launch Preview\n",
            source_surface="test",
            slot_count=1,
        )
        spec["shell"] = {
            "pending_status": "LAUNCH",
            "settled_status": "LAUNCHED",
            "workspace": "inherit",
            "next": {"fork": "session", "output": ["results"]},
            "suffix": "--gate-replay",
        }
        return spec
    if kind == "hitl":
        from sase.macro.workflow_hitl_gate import workflow_hitl_shell_spec_for_staging

        spec = workflow_hitl_shell_spec_for_staging(
            step_name="review",
            step_type="bash",
            output={"text": "ok"},
            workflow_name="wf",
            artifacts_dir=artifacts_dir,
            has_output=True,
            output_types=None,
            timeout_seconds=60.0,
        )
        spec["request_id"] = request_id
        return spec
    raise AssertionError(f"unknown kind {kind}")


def _install_real_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    workspace_num: int | None = None,
    runner_pid: int | None = None,
) -> transaction_module._CreatorContext:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    creator_dir = tmp_path / "creator"
    creator_dir.mkdir()
    (creator_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "pid": runner_pid,
                "workspace_num": workspace_num,
                "agent_session": "agent",
                "cl_name": "cl-1",
            }
        ),
        encoding="utf-8",
    )
    creator = transaction_module._CreatorContext(
        project_name="proj",
        project_file=str(tmp_path / "proj.sase"),
        artifacts_dir=str(creator_dir),
        timestamp="20261029120000",
        target_name="agent",
        durable_lane="agent",
        meta={
            "name": "agent",
            "agent_session": "agent",
            "workspace_dir": str(tmp_path / "work"),
        },
        workspace_num=workspace_num,
        runner_pid=runner_pid,
        cl_name="cl-1",
    )
    members: dict[str, str] = {}

    def fake_find(_project: str | None, gate_id: str) -> object:
        path = members.get(gate_id)
        if path is None:
            return None
        return read_gate_turn_marker("proj", path)

    real_create = create_gate_turn_member

    def tracking_member(*args: object, **kwargs: object) -> str:
        path = real_create(*args, **kwargs)
        gate_id = kwargs.get("gate_id")
        if isinstance(gate_id, str):
            members[gate_id] = path
        return path

    monkeypatch.setattr(transaction_module, "find_gate_turn_by_gate_id", fake_find)
    monkeypatch.setattr(transaction_module, "create_gate_turn_member", tracking_member)
    monkeypatch.setattr(
        transaction_module, "has_any_gate_turn", lambda *_: bool(members)
    )
    monkeypatch.setattr(
        transaction_module,
        "move_gate_turn_claim",
        lambda *_a, **_k: GateClaimMove(ClaimResult(True), None, None, "inherit"),
    )
    return creator


def _notification_ids() -> list[str]:
    return [item.id for item in load_notifications(include_dismissed=True)]


def test_create_gate_refuses_payload_mismatch_on_completed_result(
    gate_home: Path,
) -> None:
    del gate_home
    first_spec = custom_gate_spec(request_id="payload-mismatch-1")
    first = create_gate(first_spec, frozen_auto=FROZEN_MANUAL)
    other = custom_gate_spec(request_id="payload-mismatch-1")
    other["presentation"] = {**other["presentation"], "title": "A different gate"}
    with pytest.raises(GateError, match="already belongs to a different gate"):
        create_gate(other, frozen_auto=FROZEN_MANUAL)
    again = create_gate(first_spec, frozen_auto=FROZEN_MANUAL)
    assert again.request_id == first.request_id
    assert again.notification_id == first.notification_id
    assert _notification_ids() == [first.notification_id]


@pytest.mark.parametrize("kind", ["custom", "sudo", "launch", "run", "hitl"])
def test_shared_kinds_replay_reuse_request_id_and_notification(
    kind: str,
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    request_id = f"{kind}-replay-1"
    spec = _spec_from_request(_kind_spec(kind, request_id, creator.artifacts_dir))
    first = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    second = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert first.record.gate_id == second.record.gate_id == request_id
    assert first.gate.notification_id == second.gate.notification_id
    assert first.gate.kind == second.gate.kind == spec.kind
    assert second.claim_move is None
    assert _notification_ids() == [first.gate.notification_id]


def test_partial_member_finishes_missing_bundle_and_notification(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    spec = _spec_from_request(_custom_spec("partial-member-1"))
    member_dir = create_gate_turn_member(
        "proj",
        creator.meta,
        lane=creator.durable_lane,
        suffix="--gate-replay",
        prev_artifacts_timestamp=creator.timestamp,
        workspace_num=None,
        gate_id="partial-member-1",
        gate_kind="custom",
        label="Confirm guarded work",
        reason="wait for test",
        creator_agent="agent",
        timeout_seconds=0.0,
        request_fingerprint=None,
        turn=spec.turn,
    )
    monkeypatch.setattr(
        transaction_module,
        "find_gate_turn_by_gate_id",
        lambda *_: read_gate_turn_marker("proj", member_dir),
    )
    monkeypatch.setattr(
        transaction_module,
        "create_gate_turn_member",
        lambda *_a, **_k: pytest.fail("replay must not allocate another member"),
    )
    creation = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert creation.record.gate_id == "partial-member-1"
    assert creation.record.artifacts_dir == member_dir
    assert creation.gate.notification_id is not None
    assert bundle_paths("custom", "partial-member-1").creation_result.is_file()
    assert _notification_ids() == [creation.gate.notification_id]


def test_notification_retry_reuses_journal_notification_id(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    spec = _spec_from_request(_custom_spec("notify-retry-1"))
    first = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    paths = bundle_paths("custom", "notify-retry-1")
    journal = read_json_object(paths.journal)
    journal["state"] = "notification_prepared"
    atomic_write_json(paths.journal, journal)
    paths.creation_result.unlink()
    from sase.notifications import store

    Path(store.NOTIFICATIONS_FILE).write_text("", encoding="utf-8")
    store._LOAD_CACHE.clear()
    second = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert second.gate.notification_id == first.gate.notification_id
    assert _notification_ids() == [first.gate.notification_id]


def test_terminal_gate_before_receipt_does_not_republish(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    spec = _spec_from_request(_custom_spec("terminal-replay-1"))
    first = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    from sase.axe.run_agent_helpers import update_meta_field

    update_meta_field(first.record.artifacts_dir, "gate_state", "answered")
    second = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert second.record.gate_id == first.record.gate_id
    assert second.record.is_terminal
    assert second.claim_move is None
    assert _notification_ids() == [first.gate.notification_id]


def test_failed_claim_transfer_does_not_duplicate_on_replay(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(
        tmp_path, monkeypatch, workspace_num=3, runner_pid=111
    )
    moves = 0

    def failing_move(*_a: object, **_k: object) -> GateClaimMove:
        nonlocal moves
        moves += 1
        return GateClaimMove(
            ClaimResult(False, "workspace claim move failed"),
            None,
            None,
            "inherit",
        )

    monkeypatch.setattr(transaction_module, "move_gate_turn_claim", failing_move)

    def persist_failed(record, **kwargs: object):
        from sase.axe.run_agent_helpers import update_meta_field

        state = str(kwargs.get("gate_state") or "failed")
        update_meta_field(record.artifacts_dir, "gate_state", state)
        return read_gate_turn_marker("proj", record.artifacts_dir) or record

    monkeypatch.setattr(transaction_module, "settle_gate_turn", persist_failed)
    spec = _spec_from_request(_custom_spec("claim-fail-1"))
    with pytest.raises(GateTurnError, match="workspace claim move failed"):
        publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    with pytest.raises(GateTurnError, match="never published"):
        publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert moves == 1
    assert _notification_ids() == []
    assert not bundle_paths("custom", "claim-fail-1").root.exists()


def test_payload_mismatch_refuses_replay_of_existing_member(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    spec = _spec_from_request(_custom_spec("member-mismatch-1"))
    first = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    other = _custom_spec("member-mismatch-1")
    other["presentation"] = {**other["presentation"], "title": "Different payload"}
    with pytest.raises(GateError, match="already belongs to a different gate"):
        publish_gate_turn(
            _spec_from_request(other), creator=creator, frozen_auto=FROZEN_MANUAL
        )
    assert _notification_ids() == [first.gate.notification_id]


def test_kind_mismatch_refuses_without_a_second_member(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    first_spec = _spec_from_request(_custom_spec("kind-mismatch-1"))
    publish_gate_turn(first_spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    other = _kind_spec("hitl", "kind-mismatch-1", creator.artifacts_dir)
    with pytest.raises(GateTurnError, match="already belongs to a custom gate"):
        publish_gate_turn(
            _spec_from_request(other), creator=creator, frozen_auto=FROZEN_MANUAL
        )


def test_workspace_mode_mismatch_is_refused(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    inherit = _spec_from_request(_custom_spec("ws-mismatch-1", workspace="inherit"))
    publish_gate_turn(inherit, creator=creator, frozen_auto=FROZEN_MANUAL)
    released = _spec_from_request(_custom_spec("ws-mismatch-1", workspace="release"))
    with pytest.raises(GateTurnError, match="workspace policy"):
        publish_gate_turn(released, creator=creator, frozen_auto=FROZEN_MANUAL)


def test_claim_repair_runs_when_member_exists_but_claim_was_not_moved(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(
        tmp_path, monkeypatch, workspace_num=3, runner_pid=111
    )
    spec = _spec_from_request(_custom_spec("claim-repair-1"))
    member_dir = create_gate_turn_member(
        "proj",
        creator.meta,
        lane=creator.durable_lane,
        suffix="--gate-replay",
        prev_artifacts_timestamp=creator.timestamp,
        workspace_num=3,
        gate_id="claim-repair-1",
        gate_kind="custom",
        label="Confirm guarded work",
        reason="wait for test",
        creator_agent="agent",
        timeout_seconds=0.0,
        request_fingerprint=None,
        turn=spec.turn,
    )
    monkeypatch.setattr(
        transaction_module,
        "find_gate_turn_by_gate_id",
        lambda *_: read_gate_turn_marker("proj", member_dir),
    )
    monkeypatch.setattr(
        transaction_module,
        "_replay_claim_already_applied",
        lambda *_a, **_k: False,
    )
    moved: list[str] = []

    def counting_move(*_a: object, **_k: object) -> GateClaimMove:
        moved.append("moved")
        return GateClaimMove(ClaimResult(True), None, None, "inherit")

    monkeypatch.setattr(transaction_module, "move_gate_turn_claim", counting_move)
    creation = publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
    assert moved == ["moved"]
    assert creation.record.artifacts_dir == member_dir
    assert creation.gate.notification_id is not None


def test_concurrent_publication_creates_one_member_and_one_notification(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    creator = _install_real_replay(tmp_path, monkeypatch)
    monkeypatch.setattr(
        transaction_module, "gate_lane_lock", transaction_module.gate_lane_lock
    )
    spec = _spec_from_request(_custom_spec("concurrent-1"))
    results: list[object] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        try:
            results.append(
                publish_gate_turn(spec, creator=creator, frozen_auto=FROZEN_MANUAL)
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(results) == 2
    ids = {item.record.gate_id for item in results}  # type: ignore[union-attr]
    notes = {item.gate.notification_id for item in results}  # type: ignore[union-attr]
    assert ids == {"concurrent-1"}
    assert len(notes) == 1
    assert _notification_ids() == list(notes)


def test_publish_staged_gate_replays_frozen_policy_and_snapshots(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    _write_sources(tmp_path, monkeypatch)
    creator_ctx = _install_real_replay(tmp_path, monkeypatch)
    artifacts = Path(creator_ctx.artifacts_dir)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    preparation = prepare_staged_gate(
        _custom_spec("staged-replay-1"),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    assert preparation.payload is not None
    first = publish_staged_gate(
        preparation.payload,
        staged_id=preparation.staged_id,
        artifacts_dir=str(artifacts),
    )
    second = publish_staged_gate(
        preparation.payload,
        staged_id=preparation.staged_id,
        artifacts_dir=str(artifacts),
    )
    assert first.record.gate_id == second.record.gate_id == "staged-replay-1"
    assert first.gate.notification_id == second.gate.notification_id
    assert _notification_ids() == [first.gate.notification_id]


def test_mocked_replay_still_skips_a_second_claim_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record(tmp_path)
    members: list[str] = []
    moves: list[str] = []
    monkeypatch.setattr(transaction_module, "gate_lane_lock", lambda *_: nullcontext())
    monkeypatch.setattr(
        transaction_module, "find_gate_turn_by_gate_id", lambda *_: None
    )
    monkeypatch.setattr(transaction_module, "has_any_gate_turn", lambda *_: False)

    def counting_member(*_a: object, **_k: object) -> str:
        members.append("created")
        return record.artifacts_dir

    def counting_move(*_a: object, **_k: object) -> GateClaimMove:
        moves.append("moved")
        return GateClaimMove(ClaimResult(True), None, None, "inherit")

    monkeypatch.setattr(transaction_module, "create_gate_turn_member", counting_member)
    monkeypatch.setattr(transaction_module, "move_gate_turn_claim", counting_move)
    monkeypatch.setattr(transaction_module, "_record_creator_claim", lambda *_: None)
    monkeypatch.setattr(transaction_module, "_read_required_record", lambda *_: record)
    monkeypatch.setattr(
        transaction_module,
        "_record_with_gate_result",
        lambda _project, gate_record, _result: gate_record,
    )
    monkeypatch.setattr(
        transaction_module,
        "create_gate",
        lambda _spec, **_k: _creation_result(tmp_path),
    )
    creator = transaction_module._CreatorContext(
        project_name="proj",
        project_file=str(tmp_path / "proj.sase"),
        artifacts_dir=str(tmp_path / "creator"),
        timestamp="20260916115959",
        target_name="agent",
        durable_lane="agent",
        meta={"name": "agent"},
        workspace_num=None,
        runner_pid=None,
        cl_name=None,
    )
    spec = _spec_from_request(_custom_spec("intent-one"))
    first = publish_gate_turn(spec, creator=creator)
    monkeypatch.setattr(
        transaction_module, "find_gate_turn_by_gate_id", lambda *_: record
    )
    second = publish_gate_turn(spec, creator=creator)
    assert first.claim_move is not None
    assert second.claim_move is None
    assert members == ["created"]
    assert moves == ["moved"]
