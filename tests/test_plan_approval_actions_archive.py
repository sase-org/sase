"""Host-owned plan archive side effects for plan approval actions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    _archive_plan_for_approval,
    durable_plan_file_for_context,
    run_plan_side_effects,
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
