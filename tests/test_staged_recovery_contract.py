"""Recovery-contract: durable identity, replay decisions, receipt monotonicity."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.staged_handoff import (
    StagedHandoffError,
    StagedRecoveryAttempt,
    build_recovery_context,
    ensure_recovery_context,
    read_adoption_receipt,
    read_recovery_context,
    receipt_authorizes,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_staged import (
    STAGED_HANDOFF_ADOPTERS,
    dispatch_completed_staged_handoff,
)
from sase.core import staged_handoff as core_handoff
from tests._axe_run_agent_exec_helpers import make_exec_ctx

STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


def _record(tmp_path: Path) -> dict[str, object]:
    from sase.agent.staged_handoff import build_plan_staged_record

    return build_plan_staged_record(
        plan_file=str(tmp_path / "plan.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id=STAGED_ID,
        created_at="2026-10-28T12:00:00Z",
    )


def _continuation(tmp_path: Path):
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


def _write_agent_meta(artifacts: Path) -> None:
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "workspace_dir": str(artifacts.parent),
                "finalizer_status": {
                    "phase": "settled",
                    "status": "success",
                    "run_id": "controller-run-1",
                    "plan_digest": "digest-1",
                    "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )


def test_recovery_context_round_trips_and_binds_stage(tmp_path: Path) -> None:
    _ctx, _state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    meta = {"name": "agent", "workspace_dir": str(tmp_path), "model": "m"}
    context = build_recovery_context(
        record, artifacts_dir=str(artifacts), run_metadata=meta
    )
    assert context["staged_id"] == STAGED_ID
    assert context["origin_agent"] == "agent"
    assert context["origin_artifacts_dir"] == str(artifacts)

    stored = ensure_recovery_context(
        record, artifacts_dir=str(artifacts), run_metadata=meta
    )
    assert stored["staged_id"] == STAGED_ID
    assert read_recovery_context(str(artifacts), staged_id=STAGED_ID) == stored
    with pytest.raises(StagedHandoffError, match="different stage"):
        read_recovery_context(str(artifacts), staged_id=OTHER_ID)


def test_existing_context_wins_over_recovering_shell(tmp_path: Path) -> None:
    _ctx, _state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    first_meta = {"name": "agent", "workspace_dir": str(tmp_path)}
    first = ensure_recovery_context(
        record, artifacts_dir=str(artifacts), run_metadata=first_meta
    )
    second_meta = {"name": "intruder", "workspace_dir": "/elsewhere"}
    second = ensure_recovery_context(
        record, artifacts_dir=str(artifacts), run_metadata=second_meta
    )
    assert second == first
    assert second["origin_agent"] == "agent"


def test_receipt_transition_is_monotonic(tmp_path: Path) -> None:
    _ctx, _state, artifacts = _continuation(tmp_path)
    adopted = {
        "staged_id": STAGED_ID,
        "adopted_at": "2026-10-28T12:01:00Z",
        "outcome": "adopted",
        "refs": {},
    }
    held = {
        "staged_id": STAGED_ID,
        "adopted_at": "2026-10-28T12:01:00Z",
        "outcome": "handoff_not_adopted",
        "reason": "commit failed",
    }
    assert core_handoff.receipt_transition_allowed(None, adopted, STAGED_ID) is True
    assert core_handoff.receipt_transition_allowed(None, held, STAGED_ID) is True
    assert core_handoff.receipt_transition_allowed(held, adopted, STAGED_ID) is True
    assert core_handoff.receipt_transition_allowed(adopted, adopted, STAGED_ID) is True
    assert core_handoff.receipt_transition_allowed(adopted, held, STAGED_ID) is False
    with pytest.raises(Exception, match="staged_id"):
        core_handoff.receipt_transition_allowed(
            None, {**adopted, "staged_id": OTHER_ID}, STAGED_ID
        )

    write_adoption_receipt(held, artifacts_dir=str(artifacts))
    write_adoption_receipt(adopted, artifacts_dir=str(artifacts))
    with pytest.raises(StagedHandoffError, match="already owns"):
        write_adoption_receipt(held, artifacts_dir=str(artifacts))
    assert receipt_authorizes(read_adoption_receipt(str(artifacts)), STAGED_ID) is True


def test_recovery_decision_table() -> None:
    def decide(receipt, runner, killed, mode, settlement, destination):
        return core_handoff.evaluate_recovery_decision(
            {
                "schema_version": 1,
                "staged_id": STAGED_ID,
                "receipt": receipt,
                "runner": runner,
                "killed_or_discarded": killed,
                "mode": mode,
                "settlement": settlement,
                "destination": destination,
            }
        )

    assert (
        decide("adopted", "dead", False, "automatic", "settled", "absent")[
            "already_adopted"
        ]
        is True
    )
    assert (
        decide("absent", "dead", False, "automatic", "settled", "absent")["action"]
        == "adopt"
    )
    assert (
        decide("absent", "dead", False, "explicit", "settled", "pending")["action"]
        == "deliver_only"
    )
    assert (
        decide("mismatched", "dead", False, "explicit", "settled", "absent")["action"]
        == "refuse"
    )
    assert (
        decide("absent", "dead", True, "explicit", "settled", "absent")["action"]
        == "refuse"
    )
    assert (
        decide("absent", "alive", False, "automatic", "settled", "absent")["action"]
        == "hold"
    )
    assert (
        decide("absent", "unknown", False, "explicit", "settled", "absent")["action"]
        == "hold"
    )
    assert (
        decide("absent", "dead", False, "explicit", "missing", "absent")["action"]
        == "hold"
    )


def test_mismatched_receipt_is_refusal_not_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    ctx, state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_adoption_receipt(
        {
            "staged_id": OTHER_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {},
        },
        artifacts_dir=str(artifacts),
    )
    calls: list[str] = []
    monkeypatch.setitem(
        STAGED_HANDOFF_ADOPTERS, "plan", lambda *_args: calls.append("adopted")
    )

    result = dispatch_completed_staged_handoff(
        str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
    )

    assert result is not None and not result.adopted
    assert "different stage" in (result.reason or "")
    assert calls == []
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["staged_id"] == OTHER_ID


def test_dispatch_persists_recovery_and_replays_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    ctx, state, artifacts = _continuation(tmp_path)
    record = _record(tmp_path)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        STAGED_ID, "planner response", artifacts_dir=str(artifacts)
    )
    _write_agent_meta(artifacts)
    calls: list[str] = []
    monkeypatch.setitem(
        STAGED_HANDOFF_ADOPTERS,
        "plan",
        lambda _record, _meta, _cont, response: calls.append(response),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_dispatch.finalizer_settlement_refusal",
        lambda *_args, **_kwargs: None,
    )

    with patch("sase.axe.run_agent_helpers.update_meta_field"):
        first = dispatch_completed_staged_handoff(
            str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
        )
        stored = read_recovery_context(str(artifacts), staged_id=STAGED_ID)
        second = dispatch_completed_staged_handoff(
            str(artifacts), StagedInlineContinuation(ctx=ctx, state=state)
        )

    assert first is not None and first.adopted and not first.already_adopted
    assert stored is not None and stored["origin_agent"] == "agent"
    assert second is not None and second.already_adopted
    assert calls == ["planner response"]


def test_recovery_attempt_requires_live_continuation(tmp_path: Path) -> None:
    attempt = StagedRecoveryAttempt(
        staged_record=_record(tmp_path),
        run_metadata={},
        recovery_context={"staged_id": STAGED_ID},
        continuation=None,
    )
    with pytest.raises(StagedHandoffError, match="live runner"):
        attempt.require_live_continuation()
