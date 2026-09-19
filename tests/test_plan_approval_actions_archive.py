"""Host-owned plan archive side effects for plan approval actions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.failure_notifications import GATE_EXECUTION_FAILED_ACTION
from sase.notification_gates.journal import read_journal_records
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionContext,
    _archive_plan_for_approval,
    durable_plan_file_for_context,
    execute_plan_approval_response,
    run_plan_side_effects,
)
from sase.plan_gate import (
    build_plan_approval_gate_spec,
    plan_context_from_envelope,
    translate_plan_gate_response,
)
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers fixture)
    write_plan,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy
from tests.workspace_lease_helpers import (
    patched_operational_lease as _patched_operational_lease,
)


def test_archive_plan_for_approval_rejects_invalid_cutover_plan(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text("---\ntier: tale\n---\n# Plan\n", encoding="utf-8")
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(str(plan),),
        host_action_data={"project_dir": str(workspace)},
    )

    with (
        _patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda content: content,
        ),
        patch("sase._plan_archive_approval.report_plan_archive_failure"),
    ):
        saved = _archive_plan_for_approval(context, "tale")

    assert saved is None
    assert not (workspace / "sdd" / "plans" / "202608" / "plan.md").exists()


def test_approval_syncs_reviewed_bundle_to_durable_plan(tmp_path: Path) -> None:
    bundle = tmp_path / "interaction_requests" / "plan" / "request"
    bundle.mkdir(parents=True)
    reviewed = bundle / "plan.md"
    edited = VALID_TALE_PLAN.replace("requested change", "reviewed change")
    reviewed.write_text(edited, encoding="utf-8")
    durable = tmp_path / "plans" / "canonical.md"
    durable.parent.mkdir()
    durable.write_text(VALID_TALE_PLAN, encoding="utf-8")
    context = PlanApprovalActionContext(
        id="request",
        host_files=(str(reviewed),),
        host_action_data={"original_plan_file": str(durable)},
    )

    with (
        patch(
            "sase.plan_approval_actions._persist_plan_approved_metadata",
            return_value="approve",
        ),
        patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=None,
        ),
    ):
        run_plan_side_effects(context, "approve", bundle / "response.json", {})

    assert durable.read_text(encoding="utf-8") == edited


@pytest.mark.parametrize(
    ("commit_plan", "run_coder", "persisted_action"),
    [
        (False, False, "approve"),
        (False, True, "approve"),
        (True, False, "commit"),
        (True, True, "tale"),
    ],
)
def test_primary_approval_archives_only_commit_bearing_combinations(
    tmp_path: Path,
    commit_plan: bool,
    run_coder: bool,
    persisted_action: str,
) -> None:
    plan = tmp_path / f"plan-{commit_plan}-{run_coder}.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(str(plan),),
        host_action_data={},
    )
    response = {
        "action": "approve",
        "commit_plan": commit_plan,
        "run_coder": run_coder,
    }

    with (
        patch(
            "sase.plan_approval_actions._persist_plan_approved_metadata",
            return_value=persisted_action,
        ),
        patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=_ApprovedPlanArchive(
                tmp_path / "saved-plan.md",
                "plan:202608/saved-plan.md",
            ),
        ) as archive,
    ):
        run_plan_side_effects(
            context,
            "approve",
            tmp_path / "response.json",
            response,
        )

    if commit_plan:
        archive.assert_called_once_with(context, persisted_action, required=True)
        assert response["plan_archive_owner"] == "host"
        assert response["plan_archive_state"] == "archived"
        assert response["plan_archive_protocol"] == "host_v2"
        assert response["plan_archive_ref"] == "plan:202608/saved-plan.md"
        assert response["saved_plan_path"] == str(tmp_path / "saved-plan.md")
    else:
        archive.assert_not_called()
        assert response["plan_archive_owner"] == "none"
        assert response["plan_archive_state"] == "not_requested"
        assert "saved_plan_path" not in response


def test_durable_plan_file_falls_back_to_bundle_envelope(tmp_path: Path) -> None:
    durable = tmp_path / "plans" / "canonical.md"
    bundle = tmp_path / "interaction_requests" / "plan" / "request"
    bundle.mkdir(parents=True)
    reviewed = bundle / "plan.md"
    reviewed.write_text(VALID_TALE_PLAN, encoding="utf-8")
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "plan",
                "payload": {
                    "original_plan_file": str(durable),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
    )
    context = PlanApprovalActionContext(
        id="request",
        host_files=(str(reviewed),),
        host_action_data={"bundle_path": str(bundle)},
    )

    assert durable_plan_file_for_context(context) == durable


def test_archive_plan_for_approval_uses_canonical_durable_stem(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bundle_plan = tmp_path / "bundle" / "plan.md"
    bundle_plan.parent.mkdir()
    bundle_plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    durable = tmp_path / "plans" / "canonical_plan.md"
    durable.parent.mkdir()
    durable.write_text(VALID_TALE_PLAN, encoding="utf-8")
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(str(bundle_plan),),
        host_action_data={
            "project_dir": str(workspace),
            "original_plan_file": str(durable),
        },
    )

    with (
        _patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda content: content,
        ),
    ):
        saved = _archive_plan_for_approval(context, "tale")

    expected = workspace / "sdd" / "plans" / "202608" / "canonical_plan.md"
    assert saved == str(expected)
    assert isinstance(saved, _ApprovedPlanArchive)
    assert saved.plan_archive_ref == "plan:202608/canonical_plan.md"
    assert expected.is_file()


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("epic", True), ("tale", False)],
)
def test_archive_plan_for_approval_passes_expect_prompt_snapshot_for_tier(
    tmp_path: Path,
    tier: str,
    expected: bool,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = tmp_path / "plan.md"
    plan.write_text("---\ntier: tale\n---\n# Plan\n", encoding="utf-8")
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(str(plan),),
        host_action_data={"project_dir": str(workspace)},
    )

    with (
        _patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.sdd.plan_archive.archive_plan_file",
            side_effect=Exception("stop before write"),
        ) as archive_plan_file,
    ):
        _archive_plan_for_approval(context, tier)

    assert archive_plan_file.call_args.kwargs["expect_prompt_snapshot"] is expected


def test_neutral_plan_archive_failure_is_retryable_without_duplicate_option_work(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_plan(gate_home, "archive-retry.md", VALID_TALE_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "plan-archive-retry"))
    envelope = json.loads((gate.bundle_path / "request.json").read_text())
    context = plan_context_from_envelope(gate.bundle_path, envelope)
    archived = gate_home / "archived-plan.md"
    archived.write_text("# archived\n", encoding="utf-8")
    calls = {"n": 0}

    def flaky_archive(*_args: object, **_kwargs: object) -> _ApprovedPlanArchive:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(plan),
                "failed to archive approved plan: archive boom",
            )
        return _ApprovedPlanArchive(archived, "plan:202608/archived-plan.md")

    monkeypatch.setattr(
        "sase.plan_approval_actions._archive_plan_for_approval",
        flaky_archive,
    )

    with pytest.raises(PlanApprovalActionError) as failed:
        execute_plan_approval_response(
            context,
            "approve",
            commit_plan=True,
            run_coder=True,
        )

    assert failed.value.code == "plan_archive_failed"
    assert not gate.response_path.exists()
    assert (gate.bundle_path / "decision_receipt.json").is_file()
    records = list(read_journal_records(gate.bundle_path))
    assert [record["event"] for record in records].count("option_completed") == 2
    [failure] = [record for record in records if record["event"] == "attempt_failed"]
    assert failure["stage"] == "terminal_prepare"
    assert failure["code"] == "plan_archive_failed"
    assert (gate.bundle_path / failure["error_record"]).is_file()

    [notification] = [
        row
        for row in load_notifications()
        if row.action == GATE_EXECUTION_FAILED_ACTION
    ]
    assert notification.tags == ["gate", "execution", "error"]
    assert notification.action_data["request_kind"] == "plan"
    assert notification.action_data["stage"] == "terminal_prepare"
    assert notification.action_data["code"] == "plan_archive_failed"
    assert notification.action_data["recovery_actions"] == "resume,restart,cancel"
    assert (
        notification.action_data["resume_command"]
        == "sase gate answer --kind plan --id plan-archive-retry "
        "--option approve --option commit --resume"
    )
    assert (
        notification.action_data["restart_command"]
        == "sase gate answer --kind plan --id plan-archive-retry "
        "--option approve --option commit --restart"
    )
    assert (
        notification.action_data["cancel_command"]
        == "sase gate cancel --kind plan --id plan-archive-retry"
    )

    recovered = execute_gate_selection(
        gate.bundle_path,
        ["approve", "commit"],
        {},
        source="plan_response",
        retry="resume",
    )

    assert recovered.already_completed is False
    assert calls["n"] == 2
    assert gate.response_path.is_file()
    recovered_records = list(read_journal_records(gate.bundle_path))
    assert [record["event"] for record in recovered_records].count(
        "option_completed"
    ) == 2
    assert "attempt_resumed" in [record["event"] for record in recovered_records]
    assert translate_plan_gate_response(gate.bundle_path, recovered.response) == {
        "action": "approve",
        "commit_plan": True,
        "run_coder": True,
        "saved_plan_path": str(archived),
        "plan_archive_owner": "host",
        "plan_archive_state": "archived",
        "plan_archive_protocol": "host_v2",
        "plan_archive_ref": "plan:202608/archived-plan.md",
    }
    [dismissed] = [
        row
        for row in load_notifications(include_dismissed=True)
        if row.id == notification.id
    ]
    assert dismissed.dismissed is True
