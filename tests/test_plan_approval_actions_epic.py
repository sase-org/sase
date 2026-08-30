"""Headless epic-launch claims, preflight, and wait-spec resume hints."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase._plan_approval_epic import epic_launch_project, prepare_epic_launch
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalActionError,
    execute_plan_approval_response,
)
from sase.sdd._repository_transaction import SddRepositoryHealthError
from sase.xprompt.directive_edit import PromptWaitDirective
from tests.plan_validation_helpers import VALID_EPIC_PLAN


@contextmanager
def _foreign_epic_launch_lock_holder(anchor: Path, plan_file: str) -> Iterator[None]:
    """Hold the epic plan launch lock the way a foreign process would.

    ``flock`` ownership belongs to the open file description, not the
    process, so a second ``open()`` of this lock path in this same process
    is refused exactly as it would be from a separate process. The
    contended window is bounded by this ``with`` block instead of a
    wall-clock timer, which replaces forking from a multi-threaded xdist
    worker -- the actual defect behind this node's flakiness -- with an
    in-process seam.
    """
    from sase.bead.cli_work_from_plan_store import _epic_plan_launch_lock_path

    lock_path = _epic_plan_launch_lock_path(anchor)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            holder = {
                "pid": os.getpid(),
                "op": "test in-flight epic launch",
                "plan_file": plan_file,
                "started_at": datetime.now(UTC).isoformat(),
            }
            lock_file.seek(0)
            lock_file.truncate()
            json.dump(holder, lock_file, sort_keys=True)
            lock_file.flush()

            with lock_path.open("a+", encoding="utf-8") as probe:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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

    def start(*_args: object, **_kwargs: object) -> object:
        response = json.loads((response_dir / "plan_response.json").read_text())
        assert response["epic_launch_owner"] == "host"
        order.append("start")
        return SimpleNamespace(monitor_id="mon1")

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ) as resolve_project,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.epic_launch.start_epic_launch_monitor",
            side_effect=start,
        ) as start_launch,
    ):
        result = execute_plan_approval_response(context, "epic", **execute_kwargs)

    assert result.response_json["epic_launch_owner"] == "host"
    assert result.epic_launch_monitor_id == "mon1"
    assert result.epic_launch_task_id is None
    assert order == ["start"]
    assert resolve_project.call_count == 2
    resolve_project.assert_called_with(
        str(workspace),
        agent_project_file=str(tmp_path / "projects" / "canonical" / "canonical.sase"),
    )
    start_launch.assert_called_once()
    assert start_launch.call_args.kwargs["project"] == "canonical"
    assert start_launch.call_args.kwargs["origin"] == expected_origin


def test_headless_epic_approval_submits_while_inflight_launch_holds_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import epic_launch_lock_anchor

    context, _response_dir, workspace = _epic_context(tmp_path)
    plan = Path(context.host_files[0])
    anchor = epic_launch_lock_anchor(workspace)
    monkeypatch.setenv("SASE_EPIC_APPROVAL_PREFLIGHT_LOCK_TIMEOUT", "0.02")

    with _foreign_epic_launch_lock_holder(anchor, str(plan)):
        with (
            patch(
                "sase.bead.epic_launch.resolve_epic_launch_project",
                return_value="canonical",
            ),
            patch(
                "sase.running_field.get_workspace_directory",
                return_value=str(workspace),
            ),
            patch(
                "sase.bead.cli_work_from_plan_store.resolve_beads_location",
                side_effect=AssertionError(
                    "contended preflight must not materialize the sidecar"
                ),
            ),
            patch(
                "sase.bead.epic_launch.start_epic_launch_monitor",
                return_value=SimpleNamespace(monitor_id="mon-contended"),
            ) as start_launch,
        ):
            result = execute_plan_approval_response(context, "epic")

    assert result.epic_launch_monitor_id == "mon-contended"
    start_launch.assert_called_once()


def test_epic_launch_project_resolves_from_project_file_without_project_dir(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "projects" / "canonical" / "canonical.sase"
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(),
        host_action_data={"agent_project_file": str(project_file)},
    )

    with patch(
        "sase.bead.epic_launch.resolve_epic_launch_project",
        return_value="canonical",
    ) as resolve_project:
        assert epic_launch_project(context) == "canonical"

    resolve_project.assert_called_once_with(
        None,
        agent_project_file=str(project_file),
    )


def test_epic_launch_project_returns_none_without_project_identity() -> None:
    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(),
        host_action_data={},
    )

    assert epic_launch_project(context) is None


def test_prepare_epic_launch_forwards_wait_spec_to_the_monitor(
    tmp_path: Path,
) -> None:
    context, _response_dir, workspace = _epic_context(tmp_path)
    plan = context.host_files[0]
    wait_spec = PromptWaitDirective(agents=("sase-s7.2",), beads=("sase-64.3",))
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch("sase.bead.epic_launch.start_epic_launch_monitor") as start_launch,
    ):
        prepare_epic_launch(
            context,
            plan,
            mode="launch",
            response_dir=tmp_path,
            wait_spec=wait_spec,
        )

    assert start_launch.call_args.kwargs["wait_spec"] is wait_spec


def test_prepare_epic_launch_keeps_the_wait_in_the_monitor_failure_resume_hint(
    tmp_path: Path,
) -> None:
    context, _response_dir, workspace = _epic_context(tmp_path)
    plan = context.host_files[0]
    wait_spec = PromptWaitDirective(agents=("sase-s7.2",))
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.epic_launch.start_epic_launch_monitor",
            side_effect=OSError("no process"),
        ),
        pytest.raises(PlanApprovalActionError) as exc_info,
    ):
        prepare_epic_launch(
            context,
            plan,
            mode="launch",
            response_dir=tmp_path,
            wait_spec=wait_spec,
        )

    assert "--wait sase-s7.2" in str(exc_info.value)


def test_prepare_epic_launch_keeps_the_wait_in_the_unusable_store_resume_hint(
    tmp_path: Path,
) -> None:
    context, _response_dir, workspace = _epic_context(tmp_path)
    plan = context.host_files[0]
    wait_spec = PromptWaitDirective(agents=("sase-s7.2",))
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.cli_work_from_plan.require_epic_launch_store_health",
            side_effect=SddRepositoryHealthError("plans store is mid-rebase"),
        ),
        pytest.raises(PlanApprovalActionError) as exc_info,
    ):
        prepare_epic_launch(
            context,
            plan,
            mode="launch",
            response_dir=tmp_path,
            wait_spec=wait_spec,
        )

    assert "--wait sase-s7.2" in str(exc_info.value)


def test_prepare_epic_launch_keeps_the_wait_in_the_unclaimable_resume_hint(
    tmp_path: Path,
) -> None:
    context, _response_dir, _workspace = _epic_context(tmp_path)
    plan = context.host_files[0]
    wait_spec = PromptWaitDirective(agents=("sase-s7.2",))
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value=None,
        ),
        pytest.raises(PlanApprovalActionError) as exc_info,
    ):
        prepare_epic_launch(
            context,
            plan,
            mode="launch",
            response_dir=tmp_path,
            wait_spec=wait_spec,
        )

    assert "--wait sase-s7.2" in str(exc_info.value)


def test_headless_epic_submit_failure_keeps_durable_host_claim(
    tmp_path: Path,
) -> None:
    context, response_dir, workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.epic_launch.start_epic_launch_monitor",
            side_effect=OSError("no process"),
        ),
        pytest.raises(PlanApprovalActionError, match="could not start"),
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
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.cli_work_from_plan.require_epic_launch_store_health",
            side_effect=SddRepositoryHealthError("plans store is mid-rebase"),
        ),
        patch("sase.bead.epic_launch.start_epic_launch_monitor") as start_launch,
        pytest.raises(PlanApprovalActionError, match="resume with"),
    ):
        execute_plan_approval_response(context, "epic")

    start_launch.assert_not_called()
    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"


def test_headless_epic_resolution_failure_is_loud_with_resume_hint(
    tmp_path: Path,
) -> None:
    context, response_dir, _workspace = _epic_context(tmp_path)
    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            side_effect=ValueError("invalid project identity"),
        ),
        patch(
            "sase.bead.epic_launch.start_epic_launch_monitor",
        ) as start_launch,
        pytest.raises(PlanApprovalActionError) as exc_info,
    ):
        execute_plan_approval_response(context, "epic")

    assert exc_info.value.code == "epic_launch_failed"
    assert "sase bead work" in str(exc_info.value)
    assert "--yes-to-all" in str(exc_info.value)
    assert not (response_dir / "plan_response.json").exists()
    start_launch.assert_not_called()
