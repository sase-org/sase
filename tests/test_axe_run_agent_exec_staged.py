"""Staged handoff settlement, dispatch, and continuation behavior."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_staged import (
    STAGED_HANDOFF_ADOPTERS,
    StagedInlineContinuation,
    dispatch_completed_staged_handoff,
    _finalizer_settlement_refusal,
)
from sase.agent.staged_handoff import (
    build_plan_staged_record,
    read_adoption_receipt,
    receipt_authorizes,
    write_staged_handoff,
    write_staged_handoff_response,
)
from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _record(tmp_path: Path) -> dict[str, object]:
    return build_plan_staged_record(
        plan_file=str(tmp_path / "plan.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        created_at="2026-10-28T12:00:00Z",
    )


def _continuation(tmp_path: Path) -> tuple[object, LoopState, Path]:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    state = LoopState(
        current_prompt="planner prompt",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="planner prompt",
    )
    return ctx, state, artifacts


def _write_agent_meta(artifacts: Path, *, finalizer_status: str = "success") -> None:
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "workspace_dir": str(artifacts.parent),
                "finalizer_status": {
                    "phase": "settled",
                    "status": finalizer_status,
                    "run_id": "controller-run-1",
                    "plan_digest": "digest-1",
                    "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
                },
            }
        ),
        encoding="utf-8",
    )


def _write_finalizer_result(
    artifacts: Path,
    *,
    status: str = "success",
    instances: list[dict[str, str]] | None = None,
) -> None:
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": status, "instances": instances or []}),
        encoding="utf-8",
    )


def test_empty_finalizer_plan_settles_clean_turn_without_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    record = _record(tmp_path)
    _write_agent_meta(artifacts)
    _write_finalizer_result(artifacts)
    plan = SimpleNamespace(plan_digest="digest-1", entries=())

    monkeypatch.setattr(
        "sase.finalizers.plan.authenticate_resolved_finalizer_plan",
        lambda _root: plan,
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state",
        lambda *_args, **_kwargs: SimpleNamespace(repos=()),
    )

    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is None
    )


def test_empty_finalizer_plan_holds_remaining_dirty_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    record = _record(tmp_path)
    _write_agent_meta(artifacts)
    _write_finalizer_result(artifacts)
    plan = SimpleNamespace(plan_digest="digest-1", entries=())

    monkeypatch.setattr(
        "sase.finalizers.plan.authenticate_resolved_finalizer_plan",
        lambda _root: plan,
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state",
        lambda *_args, **_kwargs: SimpleNamespace(repos=(object(),)),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.repository_obligation_id",
        lambda _repo: "repo-1",
    )

    reason = _finalizer_settlement_refusal(
        record,
        artifacts_dir=str(artifacts),
        run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
    )

    assert reason == "remaining repository work has no accepted final declaration"


def test_current_dirty_repositories_are_allowed_only_with_accepted_deferrals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    record = _record(tmp_path)
    meta = {
        "name": "agent",
        "workspace_dir": str(tmp_path),
        "finalizer_status": {
            "phase": "settled",
            "status": "deferred",
            "run_id": "controller-run-1",
            "plan_digest": "digest-1",
            "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
        },
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    _write_finalizer_result(
        artifacts,
        status="deferred",
        instances=[{"instance_id": "commit", "status": "deferred"}],
    )
    (artifacts / "final_context.json").write_text(
        json.dumps(
            {
                "context": {
                    "run_id": "20261028120000",
                    "agent_id": "agent",
                    "plan_digest": "digest-1",
                }
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    plan = SimpleNamespace(
        plan_digest="digest-1",
        entries=(SimpleNamespace(instance_id="commit", provider_ref="builtin@commit"),),
    )
    dirty_repo = object()
    current_context = SimpleNamespace(
        obligations=(SimpleNamespace(kind="repository", obligation_id="repo-1"),)
    )
    accepted_submission = {
        "accepted_deferrals": [
            {"instance_id": "commit", "repo_id": "repo-1"},
        ]
    }

    monkeypatch.setattr(
        "sase.finalizers.plan.authenticate_resolved_finalizer_plan",
        lambda _root: plan,
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state",
        lambda *_args, **_kwargs: SimpleNamespace(repos=(dirty_repo,)),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.repository_obligation_id",
        lambda _repo: "repo-1",
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.load_latest_finalizer_context",
        lambda _root: current_context,
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.load_latest_finalizer_submission",
        lambda _root: accepted_submission,
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.final_submission_is_current",
        lambda **_kwargs: True,
    )

    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=meta,
        )
        is None
    )


def test_success_receipt_prevents_repeat_dispatch_and_keeps_none_inline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    ctx, state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]), "planner response", artifacts_dir=str(artifacts)
    )
    _write_agent_meta(artifacts)
    calls: list[str] = []

    def adopter(_record, _metadata, _continuation, response):
        calls.append(response)
        return None

    monkeypatch.setitem(STAGED_HANDOFF_ADOPTERS, "plan", adopter)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged._finalizer_settlement_refusal",
        lambda *_args, **_kwargs: None,
    )
    with patch("sase.axe.run_agent_helpers.update_meta_field"):
        first = dispatch_completed_staged_handoff(
            str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
        )
        second = dispatch_completed_staged_handoff(
            str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
        )

    assert first is not None and first.adopted and first.outcome is None
    assert second is not None and second.adopted and second.outcome is None
    assert second.already_adopted is True
    assert calls == ["planner response"]


def test_plan_adoption_waits_for_finalizer_settlement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    ctx, state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]), "planner response", artifacts_dir=str(artifacts)
    )
    _write_agent_meta(artifacts, finalizer_status="failed")
    _write_finalizer_result(artifacts, status="failed")
    calls: list[str] = []
    monkeypatch.setitem(
        STAGED_HANDOFF_ADOPTERS,
        "plan",
        lambda *_args: calls.append("adopted"),
    )

    dispatch = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )

    assert dispatch is not None and not dispatch.adopted
    assert calls == []
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"


def test_unsupported_staged_kind_records_held_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx, state, artifacts = _continuation(tmp_path)
    record = {**_record(tmp_path), "kind": "monitor"}
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged.read_staged_handoff",
        lambda _root: record,
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged.read_staged_handoff_response",
        lambda *_args, **_kwargs: "planner response",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged._finalizer_settlement_refusal",
        lambda *_args, **_kwargs: None,
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent", "workspace_dir": str(artifacts.parent)}),
        encoding="utf-8",
    )

    result = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )

    assert result is not None and not result.adopted
    assert result.reason == "unsupported staged handoff kind 'monitor'"
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None
    assert receipt["outcome"] == "handoff_not_adopted"
    assert receipt_authorizes(receipt, str(record["staged_id"])) is False
