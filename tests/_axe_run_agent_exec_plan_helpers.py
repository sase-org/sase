"""Shared helpers for axe run_agent_exec_plan tests."""

import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_exec_plan_accept as accept_mod
from sase.axe.run_agent_exec import AgentExecContext, LoopState


def make_ctx(
    tmp_path,
    *,
    agent_model: str | None = None,
    agent_llm_provider: str | None = "claude",
) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output"),
        workspace_num=1,
        timestamp="20260331T120000",
        update_target="",
        project_name="test_proj",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260331_120000",
        vcs_tag="#gh:sase ",
        agent_name="test_agent",
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_vcs_provider="github",
        agent_hidden=False,
        agent_meta={"model": agent_model or "default"},
        local_xprompts={},
    )


def make_state(tmp_path) -> LoopState:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(json.dumps({"suffix": ".plan"}))
    return LoopState(
        current_prompt="original prompt",
        current_role_suffix=".plan",
        current_artifacts_dir=str(artifacts),
        loop_outcome="",
        sdd_spec_path=None,
        original_prompt="original prompt",
    )


def _fake_write_sdd_spec(
    sdd_dir: Path,
    plan_name: str,
    _prompt_content: str,
    *,
    plans_root: Path | None = None,
) -> tuple[Path, Path]:
    root = plans_root or sdd_dir / "plans"
    plan_dir = root / "202603"
    return plan_dir / "prompts" / f"{plan_name}.md", plan_dir / f"{plan_name}.md"


PLAN_PATCHES = {
    "sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state": None,
    "sase.axe.run_agent_exec_plan.update_meta_suffix": None,
    "sase.axe.run_agent_exec_plan.update_meta_field": None,
    "sase.axe.run_agent_exec_plan.reset_killed": None,
    "sase.axe.run_agent_exec_plan.was_killed": lambda: False,
    "sase.axe.run_agent_exec_plan._write_plan_path_artifact": None,
    "sase.axe.run_agent_exec_plan.update_step_marker_chat_path": None,
    "sase.axe.run_agent_exec_plan.create_followup_artifacts": lambda *a, **kw: (
        "/tmp/followup"
    ),
    "sase.axe.run_agent_exec_plan.promote_to_workflow": None,
    "sase.axe.run_agent_exec_plan._store_followup_prompt_artifact": None,
    "sase.axe.run_agent_exec_plan_accept.update_meta_field": None,
    "sase.axe.run_agent_exec_plan_accept.create_followup_artifacts": lambda *a, **kw: (
        "/tmp/followup"
    ),
    "sase.axe.run_agent_exec_plan_accept.promote_to_workflow": None,
    "sase.axe.run_agent_exec_plan_accept._store_followup_prompt_artifact": None,
    "sase.axe.run_agent_exec_plan_accept._commit_sdd_files": None,
    "sase.axe.run_agent_exec_plan_accept._commit_sdd_spec": None,
    "sase.axe.run_agent_exec_plan_accept._run_epic_launch_subprocess": (
        lambda **_kwargs: accept_mod._EpicLaunchResult(0, "sase-1", ())
    ),
    "sase.axe.run_agent_exec_questions.normalize_handoff_interruption_state": None,
    "sase.axe.run_agent_exec_questions.update_meta_suffix": None,
    "sase.axe.run_agent_exec_questions.update_meta_field": None,
    "sase.axe.run_agent_exec_questions.reset_killed": None,
    "sase.axe.run_agent_exec_questions.update_step_marker_chat_path": None,
    "sase.axe.run_agent_exec_questions.create_followup_artifacts": lambda *a, **kw: (
        "/tmp/followup"
    ),
    "sase.axe.run_agent_exec_questions.promote_to_workflow": None,
    "sase.axe.run_agent_exec_questions._store_followup_prompt_artifact": None,
    "sase.llm_provider._plan_utils.handle_plan_approval": None,
    "sase.history.chat.save_chat_history": lambda **kw: "/fake/chat",
    "sase.history.chat_extras.format_extra_sections": lambda *a: "",
    "sase.history.chat_links.format_plan_as_response": lambda *a: "plan",
    "sase.vcs_provider.detect_vcs": lambda _cwd: "bare_git",
    "sase.workspace_provider.get_sdd_storage_policy_by_vcs": lambda _name: "in_tree",
    "sase.sdd.beads.ensure_beads_initialized": None,
    "sase.sdd.files.ensure_bare_git_sdd_initialized": None,
    "sase.sdd.files.write_sdd_files": None,
    "sase.sdd.files.write_sdd_spec": _fake_write_sdd_spec,
    "sase.sdd.files.expand_prompt_for_spec": lambda p: p,
    "sase.sdd.files.commit_sdd_files": None,
}


@contextmanager
def patched_plan_deps():
    """Patch heavy side effects so handle_plan_marker tests run fast."""
    patchers = []
    for target, side_effect in PLAN_PATCHES.items():
        patcher = (
            patch(target, side_effect=side_effect) if side_effect else patch(target)
        )
        patchers.append(patcher)
    mocks = [patcher.start() for patcher in patchers]
    try:
        yield mocks
    finally:
        for patcher in patchers:
            patcher.stop()
