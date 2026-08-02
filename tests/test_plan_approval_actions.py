from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase._plan_approval_epic import epic_launch_cwd
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalActionError,
    _archive_plan_for_approval,
    durable_plan_file_for_context,
    execute_plan_approval_response,
    plan_response_json_for_selection,
    resolve_plan_agent_artifacts_dir,
    run_plan_side_effects,
)
from sase.sdd._repository_transaction import SddRepositoryHealthError
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy


def _hold_epic_approval_lock(
    anchor: str,
    acquired: Any,
    release: Any,
    plan_file: str,
) -> None:
    from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock

    with epic_plan_launch_lock(
        Path(anchor),
        plan_file=plan_file,
        op="test in-flight epic launch",
    ) as locked:
        assert locked is True
        acquired.set()
        assert release.wait(5.0)


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (("approve",), {"action": "approve", "commit_plan": False, "run_coder": True}),
        (("commit",), {"action": "approve", "commit_plan": True, "run_coder": False}),
        (
            ("approve", "commit"),
            {"action": "approve", "commit_plan": True, "run_coder": True},
        ),
    ],
)
def test_runner_protocol_is_derived_from_selected_options(
    selected: tuple[str, ...], expected: dict[str, object]
) -> None:
    response, _message = plan_response_json_for_selection(selected, tier="tale")
    assert response == expected


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
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.sdd.plan_archive.archive_plan_file",
            side_effect=Exception("stop before write"),
        ) as archive_plan_file,
    ):
        _archive_plan_for_approval(context, tier)

    assert archive_plan_file.call_args.kwargs["expect_prompt_snapshot"] is expected


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


@pytest.mark.parametrize(
    ("execute_kwargs", "expected_origin"),
    [
        ({}, "api"),
        ({"epic_launch_origin": "cli"}, "cli"),
    ],
)
def test_headless_epic_approval_claims_host_ownership_before_submitting(
    tmp_path: Path,
    execute_kwargs: dict[str, str],
    expected_origin: str,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    order: list[str] = []

    def submit(*_args: object, **_kwargs: object) -> object:
        response = json.loads((response_dir / "plan_response.json").read_text())
        assert response["epic_launch_owner"] == "host"
        order.append("submit")
        return SimpleNamespace(task_id="tsk1")

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ) as resolve_cwd,
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
            side_effect=submit,
        ) as submit_launch,
    ):
        result = execute_plan_approval_response(context, "epic", **execute_kwargs)

    assert result.response_json["epic_launch_owner"] == "host"
    assert result.epic_launch_task_id == "tsk1"
    assert order == ["submit"]
    assert resolve_cwd.call_count == 2
    resolve_cwd.assert_called_with(
        str(workspace),
        agent_project_file=str(tmp_path / "projects" / "canonical" / "canonical.sase"),
    )
    submit_launch.assert_called_once()
    assert submit_launch.call_args.kwargs["cwd"] == workspace
    assert submit_launch.call_args.kwargs["origin"] == expected_origin


def test_headless_epic_approval_submits_while_inflight_launch_holds_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import epic_launch_lock_anchor

    context, _response_dir, workspace = _epic_context(tmp_path)
    plan = Path(context.host_files[0])
    anchor = epic_launch_lock_anchor(workspace)
    monkeypatch.setenv("SASE_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT", "0.02")
    process_context = multiprocessing.get_context("fork")
    holder_acquired = process_context.Event()
    release_holder = process_context.Event()
    process = process_context.Process(
        target=_hold_epic_approval_lock,
        args=(
            str(anchor),
            holder_acquired,
            release_holder,
            str(plan),
        ),
    )
    process.start()
    assert holder_acquired.wait(2.0) is True

    try:
        with (
            patch(
                "sase.bead.epic_launch.resolve_epic_launch_cwd",
                return_value=workspace,
            ),
            patch(
                "sase.bead.cli_work_from_plan_store.resolve_beads_location",
                side_effect=AssertionError(
                    "contended preflight must not materialize the sidecar"
                ),
            ),
            patch(
                "sase.bead.epic_launch.submit_epic_launch_task",
                return_value=SimpleNamespace(task_id="task-contended"),
            ) as submit_launch,
        ):
            result = execute_plan_approval_response(context, "epic")
    finally:
        release_holder.set()
        process.join(timeout=2.0)

    assert result.epic_launch_task_id == "task-contended"
    submit_launch.assert_called_once()
    assert process.exitcode == 0


def test_epic_launch_cwd_resolves_from_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_file = tmp_path / "projects" / "canonical" / "canonical.sase"
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(),
        host_action_data={"agent_project_file": str(project_file)},
    )

    with patch(
        "sase.bead.epic_launch.resolve_epic_launch_cwd",
        return_value=workspace,
    ) as resolve_cwd:
        assert epic_launch_cwd(context) == workspace

    resolve_cwd.assert_called_once_with(
        None,
        agent_project_file=str(project_file),
    )


def test_epic_launch_cwd_returns_none_without_project_identity() -> None:
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(),
        host_action_data={},
    )

    assert epic_launch_cwd(context) is None


def test_headless_epic_submit_failure_keeps_durable_host_claim(
    tmp_path: Path,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            return_value=workspace,
        ),
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
            side_effect=OSError("no process"),
        ),
        pytest.raises(PlanApprovalActionError, match="could not submit"),
    ):
        execute_plan_approval_response(context, "epic")

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"


def test_headless_epic_refuses_unusable_store_before_task_submit(
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
        patch("sase.bead.epic_launch.submit_epic_launch_task") as submit_launch,
        pytest.raises(PlanApprovalActionError, match="resume with"),
    ):
        execute_plan_approval_response(context, "epic")

    submit_launch.assert_not_called()
    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"


def test_headless_epic_resolution_failure_is_loud_with_resume_hint(
    tmp_path: Path,
) -> None:
    context, response_dir, _workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_cwd",
            side_effect=ValueError("invalid project identity"),
        ),
        patch(
            "sase.bead.epic_launch.submit_epic_launch_task",
        ) as submit_launch,
        pytest.raises(PlanApprovalActionError) as exc_info,
    ):
        execute_plan_approval_response(context, "epic")

    assert exc_info.value.code == "epic_launch_failed"
    assert "sase bead work" in str(exc_info.value)
    assert "--yes-to-all" in str(exc_info.value)
    assert not (response_dir / "plan_response.json").exists()
    submit_launch.assert_not_called()
