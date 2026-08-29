"""Runner workspace identity rebinding for VCS-allocated workspaces."""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState, _finalize_loop
from sase.axe.run_agent_exec_types import AgentExecResult
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_workspace_identity import (
    rebind_agent_workspace_identity_from_output,
)
from sase.axe.run_agent_runner_bootstrap import RunnerBootstrap
from sase.axe.run_agent_runner_launch import launch_agent_run
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.linked_repos import LinkedRepoResolution
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.workspace_provider.occupant import read_occupant_record

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_runner_retry_helpers import AGENT_INFO
from tests._running_field_helpers import create_project_file_with_running


def _prepare_placeholder_rebind(tmp_path: Path) -> tuple[AgentExecContext, Path]:
    workspace = tmp_path / "project_10"
    workspace.mkdir()
    pid = os.getpid()
    project_file = create_project_file_with_running(
        tmp_path,
        running_claims=[
            WorkspaceClaim(0, "ace-runner", "feature", pid=pid),
            WorkspaceClaim(10, "git-main", None, pid=pid),
        ],
    )
    ctx = make_exec_ctx(tmp_path, is_home_mode=False, project_name="project")
    ctx.project_file = project_file
    ctx.workspace_num = 0
    ctx.workspace_dir = str(tmp_path / "project")
    ctx.workflow_name = "ace-runner"
    ctx.cl_name = "feature"
    ctx.artifacts_timestamp = "20260828120000"
    ctx.agent_name = "identity-agent"
    ctx.agent_meta = {"pid": pid, "name": "identity-agent"}

    with (
        patch(
            "sase.linked_repos.resolve_linked_repos_for_project",
            return_value=LinkedRepoResolution(repos=()),
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
        ),
    ):
        rebind_agent_workspace_identity_from_output(
            ctx,
            artifacts_dir=ctx.artifacts_dir,
            output={
                "workspace_num": 10,
                "runner_bound_workspace": True,
            },
            workspace_dir=str(workspace),
        )

    return ctx, workspace


def test_runner_bound_workspace_rebind_moves_claim_meta_and_occupant(
    tmp_path: Path,
) -> None:
    ctx, workspace = _prepare_placeholder_rebind(tmp_path)

    claims = get_claimed_workspaces(ctx.project_file)
    assert len(claims) == 1
    assert claims[0].workspace_num == 10
    assert claims[0].pid == os.getpid()
    assert claims[0].workflow == "ace-runner"
    assert claims[0].cl_name == "feature"
    assert claims[0].artifacts_timestamp == "20260828120000"

    assert ctx.workspace_num == 10
    assert ctx.workspace_dir == str(workspace)
    assert os.environ["SASE_ACTIVE_PROJECT_DIR"] == str(workspace)
    assert os.environ["SASE_AGENT_WORKSPACE_NUM"] == "10"

    meta = json.loads((Path(ctx.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["workspace_num"] == 10
    assert meta["workspace_dir"] == str(workspace)

    occupant = read_occupant_record(str(workspace))
    assert occupant is not None
    assert occupant.pid == os.getpid()
    assert occupant.workspace_num == 10
    assert occupant.workflow == "ace-runner"
    assert occupant.agent_name == "identity-agent"
    assert occupant.cl_name == "feature"


def test_finalize_loop_returns_and_writes_rebound_workspace(
    tmp_path: Path,
) -> None:
    ctx, workspace = _prepare_placeholder_rebind(tmp_path)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "workflow_state.json").write_text(
        json.dumps({"steps": [{"status": "completed", "output": {"ok": True}}]}),
        encoding="utf-8",
    )
    state = LoopState(
        current_prompt="finish",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="finish",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.run_agent_exec_finalize.format_extra_sections",
            return_value="",
        ),
        patch(
            "sase.axe.run_agent_exec_finalize._collect_default_artifacts",
            return_value=([], 0, [], [], False),
        ),
        patch("sase.axe.run_agent_exec_finalize._enforce_artifact_retention"),
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert result.workspace_num == 10
    assert result.workspace_dir == str(workspace)
    done = json.loads((artifacts / "done.json").read_text(encoding="utf-8"))
    assert done["workspace_num"] == 10
    assert done["workspace_dir"] == str(workspace)


def test_launch_agent_run_copies_rebound_exec_workspace_identity(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    workspace = tmp_path / "project"
    rebound = tmp_path / "project_10"
    artifacts.mkdir()
    workspace.mkdir()
    rebound.mkdir()
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("work", encoding="utf-8")
    output = tmp_path / "output.txt"
    output.write_text("", encoding="utf-8")
    state = RunnerRunState(
        cl_name="feature",
        project_file=str(tmp_path / "project.sase"),
        prompt_file=str(prompt),
        output_path=str(output),
        workflow_name="ace-runner",
        timestamp="20260828_120000",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(workspace),
        workspace_num=0,
        project_name="project",
        artifacts_timestamp="20260828120000",
        artifacts_dir=str(artifacts),
        prompt="work",
        agent_name="identity-agent",
    )
    bootstrap = RunnerBootstrap(
        info=AGENT_INFO,
        agent_meta={"pid": os.getpid()},
        retry_handoff=None,
        deferred_workspace=False,
        has_dependency_wait=False,
        has_wait=False,
    )

    with (
        patch("sase.axe.run_agent_runner_launch.prepare_workspace_if_needed"),
        patch("sase.axe.run_agent_runner_launch.resolve_agent_refs_in_prompt") as refs,
        patch(
            "sase.axe.run_agent_runner_launch.build_output_variable_namespaces",
            return_value={},
        ),
        patch(
            "sase.axe.run_agent_runner_launch.capture_sdd_base_sha", return_value=None
        ),
        patch("sase.axe.run_agent_runner_launch.preload_post_gate_modules"),
        patch(
            "sase.axe.run_agent_runner_launch.code_swap_advisory_reader_lock",
            return_value=nullcontext(),
        ),
        patch(
            "sase.axe.run_agent_runner_launch.run_execution_loop",
            return_value=AgentExecResult(
                success=True,
                current_artifacts_dir=str(artifacts),
                workspace_dir=str(rebound),
                workspace_num=10,
            ),
        ),
    ):
        refs.return_value = ("work", None)
        launch_agent_run(state, bootstrap)

    assert state.workspace_num == 10
    assert state.workspace_dir == str(rebound)
