"""Shared helpers for axe run_agent_exec_plan tests."""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.transaction import GateShellCreation
from sase.notification_gates.model_results import GateCreationResult


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
    prompt_path: Path | None = None,
    yyyymm: str | None = None,
) -> tuple[Path | None, Path]:
    root = plans_root or sdd_dir / "plans"
    plan_dir = root / (yyyymm or "202603")
    return prompt_path, plan_dir / f"{plan_name}.md"


PLAN_PATCHES = {
    "sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state": None,
    "sase.axe.run_agent_exec_plan.update_meta_suffix": None,
    "sase.axe.run_agent_exec_plan.update_meta_field": None,
    "sase.axe.run_agent_exec_plan.reset_killed": None,
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
    "sase.axe.run_agent_exec_plan_accept._publish_planner_prompt_archive": (
        lambda *_args, **_kwargs: Path("/tmp/prompt-archive.md")
    ),
    "sase.axe.run_agent_exec_plan_accept._commit_sdd_files": None,
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


def _non_handoff_plan_gate_creation() -> GateShellCreation:
    """Return a synchronously-settled (non-handoff) plan gate-shell creation."""
    gate = GateCreationResult(
        schema_version=3,
        notification_id=None,
        request_id="plan-gate",
        kind="plan",
        bundle_path=Path("/tmp/plan-gate-bundle"),
        request_path=Path("/tmp/plan-gate-bundle/request.json"),
        response_path=Path("/tmp/plan-gate-bundle/response.json"),
        preview_path=None,
        continuation_mode="plan_approval",
        auto_resolution={"state": "resolved"},
        hashes={},
    )
    record = GateShellRecord(
        gate_id="plan-gate",
        member_agent_name="test_agent--gate",
        lane="test_agent",
        project_name="test_proj",
        artifacts_dir="/tmp/plan-gate-member",
        timestamp="20260827120000",
        kind="plan",
        gate_state="answered",
        start_status="TALE",
        stop_status="TALE APPROVED",
        accent="#FFD75F",
        label="Plan",
        reason="wait for reviewer",
        creator_agent="test_agent--plan",
        bundle_path="/tmp/plan-gate-bundle",
        notification_id=None,
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )
    return GateShellCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )


@contextmanager
def patch_plan_gate_shell_result(result: Any):
    """Patch the plan gate-shell seam to settle synchronously with *result*.

    Replaces the removed ``handle_plan_approval`` blocking seam: production
    code now always creates a plan gate shell and, when it settles
    in-process (no handoff), reads the result via
    ``plan_shell.plan_result_from_gate_creation``. *result* is a
    ``PlanApprovalResult`` for an accepted/feedback outcome, or ``None`` for
    a rejected one.
    """
    with (
        patch(
            "sase.plan_shell.create_plan_gate_shell",
            return_value=_non_handoff_plan_gate_creation(),
        ),
        patch(
            "sase.plan_shell.plan_result_from_gate_creation",
            return_value=result,
        ),
    ):
        yield


def _non_handoff_question_gate_creation() -> GateShellCreation:
    """Return a synchronously-settled (non-handoff) question gate-shell creation."""
    gate = GateCreationResult(
        schema_version=3,
        notification_id=None,
        request_id="question-gate",
        kind="question",
        bundle_path=Path("/tmp/question-gate-bundle"),
        request_path=Path("/tmp/question-gate-bundle/request.json"),
        response_path=Path("/tmp/question-gate-bundle/response.json"),
        preview_path=None,
        continuation_mode="agent_question",
        auto_resolution={"state": "resolved"},
        hashes={},
    )
    record = GateShellRecord(
        gate_id="question-gate",
        member_agent_name="test_agent--gate",
        lane="test_agent",
        project_name="test_proj",
        artifacts_dir="/tmp/question-gate-member",
        timestamp="20260827120000",
        kind="question",
        gate_state="answered",
        start_status="QUESTION",
        stop_status="ANSWERED",
        accent="#FFAF00",
        label="Question",
        reason="wait for reviewer",
        creator_agent="test_agent",
        bundle_path="/tmp/question-gate-bundle",
        notification_id=None,
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )
    return GateShellCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )


@contextmanager
def patch_question_gate_shell_rounds(rounds: list[Any]):
    """Patch the question gate-shell seam to settle in-process with *rounds*.

    Replaces the removed ``handle_questions_flow`` blocking seam: production
    code now always creates a question gate shell, and -- with auto-approval
    active -- settles it synchronously and continues in-process, rebuilding
    the merged Q&A from ``question_shell.question_rounds`` rather than from
    ``LoopState.qa_rounds``. *rounds* is the full settled chain (oldest
    first), including the round this call is answering.
    """
    with (
        patch(
            "sase.main.plan_approve_handler.is_auto_approve_active",
            return_value=True,
        ),
        patch(
            "sase.question_shell.resolve_question_chain_parent",
            return_value=None,
        ),
        patch(
            "sase.question_shell.create_question_gate_shell",
            return_value=_non_handoff_question_gate_creation(),
        ),
        patch(
            "sase.question_shell.question_rounds",
            return_value=rounds,
        ),
    ):
        yield
