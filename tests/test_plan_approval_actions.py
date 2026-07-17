from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalActionError,
    _archive_plan_for_approval,
    durable_plan_file_for_context,
    execute_plan_approval_response,
    resolve_plan_agent_artifacts_dir,
    run_plan_side_effects,
)
from sase.sdd._repository_transaction import SddRepositoryHealthError
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy


def test_resolve_plan_agent_artifacts_dir_from_project_file_and_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    project_dir = tmp_path / "home" / "projects" / "proj"
    artifact_dir = project_dir / "artifacts" / "ace-run" / "20260708120000"
    artifact_dir.mkdir(parents=True)
    project_file = project_dir / "proj.sase"
    project_file.write_text("WORKSPACE_DIR: /workspace/proj\n", encoding="utf-8")

    resolved = resolve_plan_agent_artifacts_dir(
        {
            "agent_project_file": str(project_file),
            "agent_timestamp": "20260708120000",
        }
    )

    assert resolved == str(artifact_dir)


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
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda content: content,
        ),
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
def test_primary_approval_archives_every_extras_combination(
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
            return_value=None,
        ) as archive,
    ):
        run_plan_side_effects(
            context,
            "approve",
            tmp_path / "response.json",
            response,
        )

    archive.assert_called_once_with(context, persisted_action)


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
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
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
    assert expected.is_file()


def _epic_context(tmp_path: Path) -> tuple[PlanApprovalActionContext, Path, Path]:
    response_dir = tmp_path / "artifacts" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    plan = tmp_path / "epic.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return (
        PlanApprovalActionContext(
            id="plan-approval",
            host_files=(str(plan),),
            host_action_data={
                "response_dir": str(response_dir),
                "project_dir": str(workspace),
                "agent_project_file": str(
                    tmp_path / "projects" / "canonical" / "canonical.sase"
                ),
                "agent_cl_name": "demo",
            },
        ),
        response_dir,
        workspace,
    )


def test_headless_epic_approval_claims_host_ownership_before_spawning(
    tmp_path: Path,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    order: list[str] = []

    def spawn(*_args: object, **_kwargs: object) -> object:
        response = json.loads((response_dir / "plan_response.json").read_text())
        assert response["epic_launch_owner"] == "host"
        order.append("spawn")
        return SimpleNamespace(pid=1234)

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.bead.epic_launch.spawn_detached_epic_launch",
            side_effect=spawn,
        ) as spawn_launch,
    ):
        result = execute_plan_approval_response(context, "epic")

    assert result.response_json["epic_launch_owner"] == "host"
    assert order == ["spawn"]
    resolve_cwd.assert_called_once_with(
        str(workspace),
        agent_project_file=str(tmp_path / "projects" / "canonical" / "canonical.sase"),
    )
    spawn_launch.assert_called_once()
    assert spawn_launch.call_args.kwargs["cwd"] == workspace


def test_headless_epic_spawn_failure_keeps_durable_host_claim(
    tmp_path: Path,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ),
        patch(
            "sase.bead.epic_launch.spawn_detached_epic_launch",
            side_effect=OSError("no process"),
        ),
        pytest.raises(PlanApprovalActionError, match="could not start"),
    ):
        execute_plan_approval_response(context, "epic")

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"


def test_headless_epic_refuses_unusable_store_before_detached_spawn(
    tmp_path: Path,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ),
        patch(
            "sase.bead.cli_work_from_plan.require_epic_launch_store_health",
            side_effect=SddRepositoryHealthError("plans store is mid-rebase"),
        ),
        patch("sase.bead.epic_launch.spawn_detached_epic_launch") as spawn_launch,
        pytest.raises(PlanApprovalActionError, match="resume with"),
    ):
        execute_plan_approval_response(context, "epic")

    spawn_launch.assert_not_called()
    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"


def test_headless_epic_resolution_failure_leaves_agent_fallback_unclaimed(
    tmp_path: Path,
) -> None:
    context, _response_dir, _workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            side_effect=ValueError("invalid project identity"),
        ),
        patch(
            "sase.bead.epic_launch.spawn_detached_epic_launch",
        ) as spawn_launch,
    ):
        result = execute_plan_approval_response(context, "epic")

    assert "epic_launch_owner" not in result.response_json
    spawn_launch.assert_not_called()
