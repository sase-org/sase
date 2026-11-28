"""Reconcile, lock, and finalize-loop cases for inactive settlement."""

from __future__ import annotations

import json
from pathlib import Path

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_monitor_staged_record,
    write_adoption_receipt,
)
from tests._staged_inactive_host_helpers import (
    FAILED_AT,
    MONITOR_ID,
    STAGED_ID,
    artifact_dir,
    write_held_receipt,
    write_monitor_stage,
    write_origin_meta,
)


def _reconcile_origin(tmp_path: Path, monkeypatch, stamp: str) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / ".sase/projects/proj/artifacts/ace-run" / stamp
    artifacts.mkdir(parents=True)
    payload = build_monitor_staged_record(
        payload={"monitor_id": MONITOR_ID},
        dirty_obligations_at_stage=[],
        staged_id=STAGED_ID,
    )
    (artifacts / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    write_adoption_receipt(
        {
            "staged_id": STAGED_ID,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": "no finalizer settlement",
        },
        artifacts_dir=str(artifacts),
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    (artifacts / "done.json").write_text('{"outcome":"failed"}')
    return artifacts


def test_reconcile_settles_failed_origin_and_stays_quiet(tmp_path, monkeypatch) -> None:
    from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs

    artifacts = _reconcile_origin(tmp_path, monkeypatch, "20261028120000")
    notified: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.senders.notify_workflow_complete",
        lambda **kwargs: notified.append(kwargs.get("sender", "")),
    )
    first = reconcile_staged_handoffs()
    assert first.adopted == 0
    assert first.held == 1
    assert not first.errors, first.errors
    marker = json.loads(
        (artifacts / ".sase_handoff_settled_inactive.json").read_text(encoding="utf-8")
    )
    assert marker["staged_id"] == STAGED_ID
    assert marker["reason"] == "origin_failed"
    # No command ran; every recovery record survives.
    from sase.procs.store import get_proc

    assert get_proc(MONITOR_ID) is None
    assert (artifacts / STAGED_HANDOFF_FILENAME).is_file()
    assert (artifacts / ".sase_handoff_adopted.json").is_file()
    second = reconcile_staged_handoffs()
    assert second.adopted == 0
    assert second.held == 1
    assert not second.errors, second.errors
    assert notified == []


def test_busy_adoption_lock_skips_settlement_without_blocking(
    tmp_path,
) -> None:
    from sase.agent.staged_handoff import acquire_adoption_lock
    from sase.axe.run_agent_exec_staged_inactive import (
        _settle_inactive_staged_handoff,
    )

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    with acquire_adoption_lock(artifact):
        skipped = _settle_inactive_staged_handoff(str(artifact), blocking=False)
    assert skipped.settled is False
    assert "another caller owns" in skipped.reason
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False
    assert _settle_inactive_staged_handoff(str(artifact)).settled is True


def test_malformed_stage_never_settles(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_inactive import observe_inactive_stage_request
    from sase.core.staged_handoff import evaluate_inactive_staged_handoff

    artifact = artifact_dir(tmp_path, "sase-1.2")
    (artifact / STAGED_HANDOFF_FILENAME).write_text("{broken", encoding="utf-8")
    write_origin_meta(artifact, "sase-1.2")
    request = observe_inactive_stage_request(str(artifact))
    assert request is not None
    assert request["stage_validity"] == "malformed"
    decision = evaluate_inactive_staged_handoff(request)
    assert decision["pending_owner"] is True
    assert decision["settlement_eligible"] is False


def test_maybe_settle_waits_for_failed_done_marker(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import maybe_settle_inactive_stage

    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    maybe_settle_inactive_stage(str(artifact), blocking=True)
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False
    (artifact / "done.json").write_text(
        json.dumps({"outcome": "failed", "finished_at": FAILED_AT}),
        encoding="utf-8",
    )
    maybe_settle_inactive_stage(str(artifact), blocking=True)
    assert (artifact / ".sase_handoff_settled_inactive.json").is_file()


def test_finalize_failed_turn_settles_without_periodic_sweep(
    monkeypatch, tmp_path
) -> None:
    from unittest.mock import patch

    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_finalize import finalize_loop
    from sase.axe.run_agent_exec_retry import RetryTracker
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    origin = Path(ctx.artifacts_dir)
    write_monitor_stage(origin)
    write_held_receipt(origin)
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    from sase.axe.run_agent_exec_staged_inactive import maybe_settle_inactive_stage

    maybe_settle_inactive_stage(str(origin), blocking=True)
    assert (origin / ".sase_handoff_settled_inactive.json").exists() is False
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=str(origin),
        loop_outcome="failed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    launched: list[str] = []
    monkeypatch.setattr(
        "sase.monitor.start_launch.submit_proc_request",
        lambda *args, **kwargs: launched.append("submit") or None,
    )
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(origin / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)
    done = json.loads((origin / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "failed"
    marker = json.loads(
        (origin / ".sase_handoff_settled_inactive.json").read_text(encoding="utf-8")
    )
    assert marker["staged_id"] == STAGED_ID
    assert (origin / STAGED_HANDOFF_FILENAME).is_file()
    assert launched == []


def test_finalize_successful_turn_does_not_settle(monkeypatch, tmp_path) -> None:
    from unittest.mock import patch

    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_finalize import finalize_loop
    from sase.axe.run_agent_exec_retry import RetryTracker
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    origin = Path(ctx.artifacts_dir)
    write_monitor_stage(origin)
    write_held_receipt(origin)
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    (origin / "response.md").write_text("ok\n", encoding="utf-8")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=str(origin),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(origin / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.run_agent_exec_finalize._is_workflow_noop",
            return_value=False,
        ),
    ):
        finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)
    done = json.loads((origin / "done.json").read_text(encoding="utf-8"))
    assert done["outcome"] == "completed"
    assert (origin / ".sase_handoff_settled_inactive.json").exists() is False
