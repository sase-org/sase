"""Coder recovery for gateless ``sase plan approve`` runs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.agent_session_attach import AgentSessionAttachLaunchPlan
from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRefusal,
    DirectApprovalRefused,
    DirectApprovalRequest,
)
from sase.main.plan_direct_approval_recovery import (
    CoderRecovery,
    PriorCoder,
    _gate_followup_coder,
    evaluate_approval_recovery,
    prior_coder_word,
)
from sase.main.plan_pending_diagnosis import PlanGateHistory
from sase.plan_approval_receipts import (
    DirectApprovalReceipt,
    read_direct_approval_receipt,
    write_direct_approval_receipt,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture(autouse=True)
def _no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)


@pytest.fixture()
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    return home


def _local_plan(home: Path, name: str = "work.md") -> Path:
    plan = home / "plans" / "202609" / name
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    return plan


def _handled_history(**overrides: object) -> PlanGateHistory:
    fields: dict[str, object] = {
        "kind": "handled",
        "action": "approve",
        "age": " (7m ago)",
        "notification_id": "gate123",
        "bundle_path": Path("/tmp/gate-bundle"),
        "action_data": {"agent_name": "0sk"},
    }
    fields.update(overrides)
    return PlanGateHistory(**fields)  # type: ignore[arg-type]


def _failed_prior(name: str = "0sk--code") -> PriorCoder:
    return PriorCoder(name=name, state="ended", outcome="failed", age="14m ago")


def _patch_facts(monkeypatch: pytest.MonkeyPatch, action: str, ref: str | None) -> None:
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis._gate_approval_facts",
        lambda bundle_path: (action, ref),
    )


# --- evaluate: verdicts ------------------------------------------------------


def test_handled_tale_failed_coder_recovers(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    history = _handled_history()
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled", "notification_id": "gate123"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: _failed_prior(name),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.plan_argument == "plan:202609/work.md"
    assert recovery.approved_action == "tale"
    assert recovery.approved_age == "7m ago"
    assert recovery.gate_id == "gate123"
    assert [prior.name for prior in recovery.prior_coders] == ["0sk--code"]


def test_live_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: PriorCoder(name=name, state="live", outcome="running"),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=_handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "live"
    assert recovery.refusal_code == "coder_running"


def test_succeeded_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "approve", None)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: PriorCoder(
            name=name, state="succeeded", outcome="completed", age="2h ago"
        ),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=_handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "succeeded"
    assert recovery.refusal_code == "already_implemented"
    assert recovery.plan_argument == str(plan)


def test_committed_done_with_unknown_coder_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._committed_plan_is_done",
        lambda ref, cwd: True,
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=_handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "succeeded"
    assert recovery.prior_coders == ()


def test_missing_gate_turn_and_no_code_recovers(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    _patch_facts(monkeypatch, "tale", "plan:202609/work.md")
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._committed_plan_is_done",
        lambda ref, cwd: False,
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=_handled_history(), project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.prior_coders == ()


def test_commit_receipt_with_launch_error_recovers(sase_home_dir: Path) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="commit",
            approved_at="2026-09-25T19:00:00+00:00",
            plan_archive_ref="plan:202609/work.md",
            coder_error="boom",
        )
    )
    history = PlanGateHistory(kind="direct", action="commit", age=" (5m ago)")

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"
    assert recovery.approved_action == "commit"


def test_gate_coder_used_when_receipt_lost_race(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="none",
            plan_archive_ref="plan:202609/work.md",
            coder_error="gate race-gate was answered concurrently; no coder launched",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age=" (5m ago)")
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_entry_for_plan",
        lambda local, gate_id: {"state": "already_handled"},
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._gate_followup_coder",
        lambda entry, project: "0sk--code",
    )
    states = {"mode": "failed"}
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: (
            _failed_prior(name)
            if states["mode"] == "failed"
            else PriorCoder(name=name, state="live", outcome="running")
        ),
    )

    failed = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )
    assert failed is not None
    assert failed.verdict == "recover"

    states["mode"] = "live"
    running = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )
    assert running is not None
    assert running.verdict == "live"


def test_second_run_with_live_replacement_refuses(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="session",
            plan_archive_ref="plan:202609/work.md",
            coder_agent="0sk--2",
            coder_pid=4242,
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age="")
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery._classify_prior_coder",
        lambda name: (
            PriorCoder(name=name, state="live", outcome="running")
            if name == "0sk--2"
            else PriorCoder(name=name, state="missing")
        ),
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "live"
    assert [prior.name for prior in recovery.prior_coders] == [
        "0sk--2",
        "0sk--code",
    ]


def test_crash_receipt_recovers_again(sase_home_dir: Path) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            route="session",
            plan_archive_ref="plan:202609/work.md",
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )
    history = PlanGateHistory(kind="direct", action="tale", age="")

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=history, project="demo"
    )

    assert recovery is not None
    assert recovery.verdict == "recover"


@pytest.mark.parametrize("action", ["epic", "reject", "feedback", "cancel"])
def test_non_coder_histories_keep_refusal(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    plan = _local_plan(sase_home_dir)
    _patch_facts(monkeypatch, action, None)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.gate_history_for_plan",
        lambda local: [{"state": "already_handled"}],
    )

    recovery = evaluate_approval_recovery(
        local_plan=plan, history=_handled_history(action=action), project="demo"
    )

    assert recovery is None


def test_direct_non_coder_receipt_keeps_refusal(sase_home_dir: Path) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="reject",
            approved_at="2026-09-25T19:00:00+00:00",
        )
    )
    history = PlanGateHistory(kind="direct", action="reject", age="")

    assert (
        evaluate_approval_recovery(local_plan=plan, history=history, project="demo")
        is None
    )


def test_fresh_histories_keep_refusal(sase_home_dir: Path) -> None:
    plan = _local_plan(sase_home_dir)
    for kind in ("none", "orphaned", "expired"):
        history = PlanGateHistory(kind=kind)  # type: ignore[arg-type]
        assert (
            evaluate_approval_recovery(local_plan=plan, history=history, project="demo")
            is None
        )


# --- gate follow-up ----------------------------------------------------------


def test_gate_followup_prefers_verified_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.paths import sase_projects_dir  # noqa: F401

    shell_dir = tmp_path / "shell"
    shell_dir.mkdir()
    (shell_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_notification_id": "gate123",
                "gate_followup_agent": "0sk--code",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.core.agent_artifact_paths.resolve_agent_artifact_timestamp_path",
        lambda project, workflow, suffix: shell_dir,
    )
    entry: dict[str, object] = {
        "notification_id": "gate123",
        "action_data": {"raw_suffix": "20260925000000", "agent_name": "0sk"},
    }

    assert _gate_followup_coder(entry, "demo") == "0sk--code"


def test_gate_followup_falls_back_to_registered_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.names.lookup_registered_name",
        lambda name: (
            {"artifacts_dir": "/x", "state": "reserved"}
            if name == "0sk--code"
            else None
        ),
    )
    entry: dict[str, object] = {
        "notification_id": "gate123",
        "action_data": {"agent_name": "0sk"},
    }

    assert _gate_followup_coder(entry, "demo") == "0sk--code"


def test_prior_coder_words() -> None:
    assert (
        prior_coder_word(PriorCoder(name="c", state="live", outcome="running"))
        == "running"
    )
    assert (
        prior_coder_word(
            PriorCoder(name="c", state="ended", outcome="failed", age="14m ago")
        )
        == "failed 14m ago"
    )
    assert (
        prior_coder_word(
            PriorCoder(name="c", state="succeeded", outcome="completed", age="2h ago")
        )
        == "completed 2h ago"
    )
    assert prior_coder_word(PriorCoder(name="c", state="missing")) == "not found"


# --- resolver ----------------------------------------------------------------


def _attach_plan(*, running: bool = False) -> AgentSessionAttachLaunchPlan:
    return AgentSessionAttachLaunchPlan(
        parent_arg="0sk",
        suffix_arg="code",
        parent_name="0sk",
        parent_base="0sk",
        parent_timestamp="20260925000000",
        parent_artifacts_dir="/tmp/planner",
        role_suffix="--code",
        agent_name="0sk--code",
        agent_session_role="code",
        parent_agent_session_member_name="0sk",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="demo",
        parent_is_running=running,
    )


def test_resolver_returns_recovery_plan(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = _local_plan(sase_home_dir)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: _handled_history(),
    )
    recovery = CoderRecovery(
        verdict="recover",
        prior_coders=(_failed_prior(),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: recovery,
    )
    monkeypatch.setattr(
        "sase.agent.agent_session_attach.resolve_agent_session_attach_plan",
        lambda directive, project_name=None: _attach_plan(),
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(selector=str(plan), project="demo")
    )

    assert not isinstance(outcome, (DirectApprovalRefusal, type(None)))
    assert outcome.recovery is recovery
    assert outcome.predicted_plan_ref == "plan:202609/work.md"
    assert "#coder(plan:202609/work.md)" in outcome.coder_prompt_preview
    assert "archive_approved_plan" not in outcome.coder_prompt_preview


def test_resolver_live_verdict_refuses_coder_running(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = _local_plan(sase_home_dir)
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: _handled_history(),
    )
    recovery = CoderRecovery(
        verdict="live",
        prior_coders=(PriorCoder(name="0sk--code", state="live", outcome="running"),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
        refusal_code="coder_running",
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: recovery,
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(selector=str(plan), project="demo")
    )

    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "coder_running"
    assert "already approved and its coder is running" in outcome.header
    assert outcome.detail_lines[2] == "coder   0sk--code · running"
    assert outcome.hints == ("sase agent show 0sk--code",)


def test_resolver_explicit_commit_keeps_handled_refusal(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval import resolve_direct_approval

    plan = _local_plan(sase_home_dir)
    history = _handled_history()
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: history,
    )
    evaluate = MagicMock(return_value=None)
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        evaluate,
    )

    outcome = resolve_direct_approval(
        DirectApprovalRequest(
            selector=str(plan), kind="commit", kind_explicit=True, project="demo"
        )
    )

    assert isinstance(outcome, DirectApprovalRefusal)
    assert outcome.code == "conflict_already_handled"
    evaluate.assert_not_called()


# --- executor ----------------------------------------------------------------


def _recovery_plan(home: Path, **overrides: object) -> DirectApprovalPlan:
    source = _local_plan(home)
    recovery = CoderRecovery(
        verdict="recover",
        prior_coders=(_failed_prior(),),
        approved_action="tale",
        approved_age="7m ago",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
    )
    fields: dict[str, object] = {
        "request": DirectApprovalRequest(selector=str(source), project="demo"),
        "kind": "tale",
        "source_path": source,
        "location": "proposal",
        "name": "work",
        "title": "Work",
        "size": "small",
        "project": "demo",
        "project_tag": "+demo",
        "planner": "0sk",
        "gate": None,
        "placement": CoderPlacement(
            mode="session",
            parent="0sk",
            member_name="0sk--2",
            agent_session="0sk",
        ),
        "model_directive": "@small",
        "bead": None,
        "predicted_plan_ref": "plan:202609/work.md",
        "coder_prompt_preview": "+demo %model:@small #coder(plan:202609/work.md)",
        "recovery": recovery,
    }
    fields.update(overrides)
    return DirectApprovalPlan(**fields)  # type: ignore[arg-type]


def _launch_result(home: Path) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=4242,
        workspace_num=1,
        workspace_dir=str(home),
        output_path=str(home / "out.log"),
        agent_name="0sk--2",
    )


def test_executor_launches_one_coder_and_writes_receipt(
    sase_home_dir: Path,
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    plan = _recovery_plan(sase_home_dir)
    launched = _launch_result(sase_home_dir)
    seen_env: dict[str, str] = {}
    with (
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=lambda prompt, extra_env=None, **kwargs: (
                seen_env.update(extra_env or {}),
                [launched],
            )[1],
        ) as launch,
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            side_effect=AssertionError("recovery never archives"),
        ),
        patch(
            "sase.notification_gates.executor_cancellation.cancel_gate",
            side_effect=AssertionError("recovery never retires gates"),
        ),
        patch(
            "sase.plan_approval_actions.record_plan_approval_metadata",
            side_effect=AssertionError("recovery never records metadata"),
        ),
    ):
        outcome = execute_coder_recovery(plan)

    assert launch.call_count == 1
    assert outcome.coder is launched
    assert seen_env.get("SASE_PLAN") == str(plan.source_path)
    assert "SASE_PLAN" in launch.call_args[1].get("extra_env", {})
    receipt = read_direct_approval_receipt(plan.source_path)
    assert receipt is not None
    assert receipt.replaced_coders == ("0sk--code",)
    assert receipt.coder_agent == "0sk--2"
    assert receipt.coder_pid == 4242
    assert receipt.recovered_gate_id == "gate123"
    assert receipt.plan_archive_ref == "plan:202609/work.md"


def test_executor_launch_failure_records_error(sase_home_dir: Path) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    plan = _recovery_plan(sase_home_dir)
    with patch(
        "sase.agent.launch_cwd.launch_agents_from_cwd",
        side_effect=RuntimeError("boom"),
    ):
        outcome = execute_coder_recovery(plan)

    assert outcome.coder is None
    assert outcome.coder_error == "boom"
    receipt = read_direct_approval_receipt(plan.source_path)
    assert receipt is not None
    assert receipt.coder_error == "boom"
    assert receipt.replaced_coders == ("0sk--code",)


def test_executor_lock_recheck_refuses_without_launching(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery

    plan = _recovery_plan(sase_home_dir)
    live = CoderRecovery(
        verdict="live",
        prior_coders=(PriorCoder(name="0sk--2", state="live", outcome="running"),),
        approved_action="tale",
        approved_age="",
        gate_id="gate123",
        plan_argument="plan:202609/work.md",
        refusal_code="coder_running",
    )
    monkeypatch.setattr(
        "sase.main.plan_pending_diagnosis.classify_plan_gate_history",
        lambda local: _handled_history(),
    )
    monkeypatch.setattr(
        "sase.main.plan_direct_approval_recovery.evaluate_approval_recovery",
        lambda **kwargs: live,
    )
    launch = MagicMock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr("sase.agent.launch_cwd.launch_agents_from_cwd", launch)

    with pytest.raises(DirectApprovalRefused) as exc_info:
        execute_coder_recovery(plan)

    assert exc_info.value.refusal.code == "coder_running"
    launch.assert_not_called()


def test_executor_agent_guard(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_run import execute_coder_recovery
    from sase.plan_approval_actions import PlanApprovalActionError

    monkeypatch.setenv("SASE_AGENT", "1")
    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_coder_recovery(_recovery_plan(sase_home_dir))
    assert exc_info.value.code == "agent_launch_denied"


# --- diagnosis ----------------------------------------------------------------


def test_handled_age_uses_handled_at(
    sase_home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time as time_module

    from sase.main.plan_pending_diagnosis import classify_plan_gate_history
    from sase.notifications import pending_actions
    from sase.notifications.models import Notification
    from sase.notifications.store import append_notification

    plan = _local_plan(sase_home_dir)
    created = time_module.time() - 42 * 60
    handled = time_module.time() - 7 * 60
    with monkeypatch.context() as patcher:
        patcher.setattr(time_module, "time", lambda: created)
        append_notification(
            Notification(
                id="abcdef01-full",
                timestamp="2026-09-25T19:00:00+00:00",
                sender="test",
                notes=["note"],
                files=[str(plan)],
                action="PlanApproval",
                action_data={
                    "agent_name": "0sk",
                    "original_plan_file": str(plan),
                    "response_dir": str(sase_home_dir / "resp"),
                },
            )
        )
    pending_actions.mark_already_handled(
        "abcdef01-full", source="test", action="approve", now=handled
    )

    history = classify_plan_gate_history(plan)

    assert history.kind == "handled"
    assert history.age == " (7m ago)"


def test_response_refines_approve_commit_to_tale(tmp_path: Path) -> None:
    from sase.main.plan_pending_diagnosis import (
        _gate_approval_facts,
        refined_gate_history_action,
    )

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "request.json").write_text(
        json.dumps({"request_id": "g1", "kind": "tale"}), encoding="utf-8"
    )
    (bundle / "response.json").write_text(
        json.dumps(
            {
                "selected_option_ids": ["approve", "commit"],
                "option_results": [
                    {
                        "id": "approve",
                        "result": {"plan_archive_ref": "plan:202609/work.md"},
                    },
                    {"id": "commit", "result": {}},
                ],
            }
        ),
        encoding="utf-8",
    )

    action, ref = _gate_approval_facts(bundle)

    assert action == "tale"
    assert ref == "plan:202609/work.md"
    history = PlanGateHistory(kind="handled", action="approve", bundle_path=bundle)
    assert refined_gate_history_action(history) == "tale"


def test_inspect_hint_prefers_committed_ref(tmp_path: Path) -> None:
    from sase.main.plan_pending_diagnosis import inspect_command_for_located_plan

    history = PlanGateHistory(
        kind="handled", action="tale", bundle_path=tmp_path / "missing"
    )
    assert (
        inspect_command_for_located_plan(
            Path("/home/u/.sase/plans/202609/work.md"), history
        )
        == "sase plan show /home/u/.sase/plans/202609/work.md"
    )


def test_refusal_hint_prints_once(capsys: pytest.CaptureFixture[str]) -> None:
    from sase.main.plan_approve_render import render_direct_approval_refusal
    from sase.main.plan_direct_approval import DirectApprovalRefusal

    hint = "sase plan show plan:202609/work.md"
    render_direct_approval_refusal(
        DirectApprovalRefusal(
            code="conflict_already_handled",
            header="work is not awaiting approval",
            detail_lines=(f"Inspect it with: {hint}",),
            hints=(hint,),
        )
    )

    assert capsys.readouterr().err.count(hint) == 1


def test_recovery_receipt_wording(sase_home_dir: Path) -> None:
    from sase.main.plan_pending_diagnosis import direct_approval_via_text

    plan = _local_plan(sase_home_dir)
    assert direct_approval_via_text(plan) == "via sase plan approve"
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            replaced_coders=("0sk--code",),
            recovered_gate_id="gate123",
        )
    )

    assert direct_approval_via_text(plan) == "coder relaunched via sase plan approve"


def test_receipt_round_trips_recovery_fields(sase_home_dir: Path) -> None:
    plan = _local_plan(sase_home_dir)
    write_direct_approval_receipt(
        DirectApprovalReceipt(
            plan_path=str(plan),
            action="tale",
            approved_at="2026-09-25T19:00:00+00:00",
            replaced_coders=("0sk--code", "0sk--2"),
            recovered_gate_id="gate123",
        )
    )

    receipt = read_direct_approval_receipt(plan)

    assert receipt is not None
    assert receipt.replaced_coders == ("0sk--code", "0sk--2")
    assert receipt.recovered_gate_id == "gate123"
