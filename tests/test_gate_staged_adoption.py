"""Dispatcher settlement and staged gate adoption from persisted creator context."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    read_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_staged import (
    CARRIED_CUSTODY_META_KEY,
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
)
from sase.axe.run_agent_exec_staged_gate import handle_staged_gate_marker
from sase.gate_turn.staged_contract import prepare_staged_gate
from sase.gate_turn.transaction import GateTurnCreation
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests.gate_turn.test_staged_contract import _creator, _request, _write_sources
from tests.gate_turn.test_transaction_gate_intent import _creation_result, _record
from tests.test_staged_custody_adoption import (
    DIGEST_MAIN,
    _artifacts,
    _carry_evidence,
    _context,
    _continuation,
    _meta,
    _patch_common,
    _write_context_json,
    _write_meta,
    _write_result,
)


PROVIDER_RESPONSE = "provider response that must survive adoption"


def _settled_gate_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, Any]]:
    artifacts = _artifacts(tmp_path)
    record = _stage_gate(tmp_path, artifacts, monkeypatch)
    # ``write_staged_handoff`` admits the stage and may rewrite
    # ``finalizer_result.json``; settlement evidence must land after that.
    meta = _meta(artifacts)
    meta.update(
        {
            "pid": 99,
            "workspace_num": 2,
            "cl_name": "cl-1",
            "agent_session": "agent",
        }
    )
    _write_meta(artifacts, meta)
    _write_context_json(artifacts)
    _write_result(artifacts, evidence=[_carry_evidence("repo-1", DIGEST_MAIN)])
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    _patch_common(
        monkeypatch,
        context=_context(kind="gate"),
        dirty_ids=["repo-1"],
        submission={"accepted_deferrals": []},
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.repository_obligation_id",
        lambda _repo: "repo-1",
    )
    return artifacts, record


def _stage_gate(
    tmp_path: Path, artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    _write_sources(tmp_path, monkeypatch)
    preparation = prepare_staged_gate(
        _request(request_id="staged-gate-1"),
        creator=_creator(str(artifacts)),
        artifacts_dir=str(artifacts),
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )
    assert preparation.record is not None
    write_staged_handoff(preparation.record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(preparation.record["staged_id"]),
        PROVIDER_RESPONSE,
        artifacts_dir=str(artifacts),
    )
    return preparation.record


def _fake_creation(tmp_path: Path, *, artifacts_dir: str) -> GateTurnCreation:
    record = replace(
        _record(tmp_path), artifacts_dir=artifacts_dir, gate_id="staged-gate-1"
    )
    return GateTurnCreation(
        gate=_creation_result(tmp_path),
        record=record,
        project_file=str(tmp_path / "proj.sase"),
        claim_move=None,
        cl_name=None,
    )


def test_unsatisfied_finalizers_do_not_publish_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, _staged = _settled_gate_artifacts(tmp_path, monkeypatch)
    del _staged
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged._finalizer_settlement_refusal",
        lambda *_args, **_kwargs: "finalizer controller did not settle successfully",
    )
    published: list[str] = []
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_gate.publish_staged_gate",
        lambda *_a, **_k: published.append("published"),
    )
    continuation = _continuation(tmp_path, artifacts)

    result = dispatch_completed_staged_handoff(str(artifacts), continuation)

    assert result is not None and not result.adopted
    assert published == []
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"


def test_successful_settlement_publishes_once_and_records_gate_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, record = _settled_gate_artifacts(tmp_path, monkeypatch)
    member = tmp_path / "gate-member"
    member.mkdir()
    (member / "agent_meta.json").write_text("{}", encoding="utf-8")
    creation = _fake_creation(tmp_path, artifacts_dir=str(member))
    publishes: list[str] = []
    persist_flags: list[bool] = []

    def publish(*_a: object, **_k: object) -> GateTurnCreation:
        publishes.append("once")
        return creation

    def fake_handle(
        _data: object,
        _ctx: object,
        _state: object,
        *,
        persist_chat: bool = True,
    ) -> str:
        persist_flags.append(persist_chat)
        return "gated"

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_gate.publish_staged_gate", publish
    )
    monkeypatch.setattr("sase.axe.run_agent_exec_gate.handle_gate_marker", fake_handle)
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    continuation = _continuation(tmp_path, artifacts)

    first = dispatch_completed_staged_handoff(str(artifacts), continuation)
    second = dispatch_completed_staged_handoff(str(artifacts), continuation)

    assert first is not None and first.adopted and first.outcome == "gated"
    assert second is not None and second.already_adopted
    assert publishes == ["once"]
    assert persist_flags == [False]
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
    assert receipt["refs"]["gate_id"] == "staged-gate-1"
    assert receipt["refs"]["member_artifacts_dir"] == str(member)
    assert receipt["refs"]["loop_outcome"] == "gated"
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta[CARRIED_CUSTODY_META_KEY][0]["carried_to"] == str(member)
    assert record["kind"] == "gate"


def test_publication_failure_writes_held_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, _staged = _settled_gate_artifacts(tmp_path, monkeypatch)
    del _staged

    def boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("bundle write failed")

    monkeypatch.setattr("sase.axe.run_agent_exec_staged_gate.publish_staged_gate", boom)
    continuation = _continuation(tmp_path, artifacts)

    with pytest.raises(RuntimeError, match="bundle write failed"):
        dispatch_completed_staged_handoff(str(artifacts), continuation)

    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"
    assert "bundle write failed" in str(receipt.get("reason"))


def test_handle_gate_marker_does_not_write_synthetic_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent"}), encoding="utf-8"
    )
    member = tmp_path / "member"
    member.mkdir()
    (member / "agent_meta.json").write_text("{}", encoding="utf-8")
    creation = _fake_creation(tmp_path, artifacts_dir=str(member))
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_gate.publish_staged_gate",
        lambda *_a, **_k: creation,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.normalize_handoff_interruption_state",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.finalize_handoff_artifacts_as_completed",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.update_meta_field",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr("sase.axe.run_agent_exec_gate.reset_killed", lambda: None)
    saved: list[str] = []
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.save_chat_history",
        lambda **kwargs: saved.append(str(kwargs.get("response"))) or "/fake/chat",
    )
    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(artifacts),
        agent_name="agent",
    )
    state = LoopState(
        current_prompt="p",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="p",
    )
    adopted = handle_staged_gate_marker(
        {
            "staged_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "kind": "gate",
            "successor_workspace": "inherit",
            "payload": {"request_id": "staged-gate-1"},
        },
        ctx,
        StagedInlineContinuation(ctx=ctx, state=state),
        provider_response=PROVIDER_RESPONSE,
    )
    assert adopted.outcome == "gated"
    assert saved == []
    assert adopted.member_artifacts_dir == str(member)
    assert adopted.retains_workspace is True
