"""Questions marker handling for the agent execution loop."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_exec_plan import (
    agent_name_for_suffix,
    record_workflow_metadata,
)
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    assemble_question_followup_prompt,
    create_followup_artifacts,
    finalize_handoff_artifacts_as_completed,
    merge_qa_for_prompt,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_meta_suffix,
    update_step_marker_chat_path,
)
from sase.axe.run_agent_successor import SuccessorRequest, continue_as_successor
from sase.axe.runner_signals import reset_killed
from sase.plan_chain import (
    AGENT_FAMILY_SEPARATOR,
    agent_family_base,
    agent_family_role_for_suffix,
    agent_family_suffix_token,
    canonical_plan_chain_suffix,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_store_followup_prompt_artifact = store_followup_prompt_artifact


def _interrupted_phase_meta(
    artifacts_dir: str,
    fallback_meta: dict[str, Any],
) -> dict[str, Any]:
    """Return the interrupted phase's ``agent_meta.json`` as follow-up base meta.

    A code-phase question continuation must inherit the concrete worker
    provider/model ``handle_accepted_plan`` recorded for the interrupted phase,
    not the planner metadata carried in ``ctx.agent_meta``. Falls back to
    *fallback_meta* when the file is missing or unreadable.
    """
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            loaded = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback_meta
    return loaded if isinstance(loaded, dict) and loaded else fallback_meta


def _meta_family_role(meta: dict[str, Any]) -> str | None:
    role = meta.get("agent_family_role")
    return role if isinstance(role, str) and role else None


def _question_interrupted_suffix_and_role(
    state: LoopState,
    base_meta: dict[str, Any],
) -> tuple[str, str | None]:
    """Return the interrupted shell suffix and role for a question handoff."""
    interrupted_suffix = canonical_plan_chain_suffix(state.current_role_suffix)
    if interrupted_suffix is None:
        interrupted_suffix = canonical_plan_chain_suffix(base_meta.get("role_suffix"))
    if interrupted_suffix is None:
        interrupted_suffix = f"{AGENT_FAMILY_SEPARATOR}0"
    if state.agent_step == 1:
        update_meta_suffix(state.current_artifacts_dir, interrupted_suffix)

    interrupted_role = _meta_family_role(base_meta)
    if interrupted_role is None:
        interrupted_role = agent_family_role_for_suffix(interrupted_suffix)
    if interrupted_role is None:
        token = agent_family_suffix_token(interrupted_suffix)
        interrupted_role = (
            token
            if token is not None and token != "q" and not token.isdigit()
            else "agent"
        )
    return interrupted_suffix, interrupted_role


def _question_successor_fallback_token(reserved_suffixes: tuple[str, ...]) -> str:
    """Return the first numeric suffix token not already used in this handoff."""
    reserved = {f"{AGENT_FAMILY_SEPARATOR}0"}
    for suffix in reserved_suffixes:
        canonical = canonical_plan_chain_suffix(suffix)
        reserved.add(canonical or suffix)
    token = 0
    while f"{AGENT_FAMILY_SEPARATOR}{token}" in reserved:
        token += 1
    return str(token)


def handle_questions_marker(
    q_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Handle a questions marker left by ``sase questions``.

    The runner creates a question gate shell during marker adoption: it
    never writes ``pending_question.json``, never yields or reacquires a
    runner slot, and never calls ``wait_for_gate``. Either the runner
    terminalizes as ``DONE`` (delegated to :func:`handle_gate_marker`,
    exactly as any other gate shell), or -- on the ``%auto`` short-circuit,
    where the gate already settled synchronously inside creation -- it
    continues in-process at the cost of exactly one agent.
    """
    normalize_handoff_interruption_state(state.current_artifacts_dir)
    finalize_handoff_artifacts_as_completed(state.current_artifacts_dir)
    reset_killed()

    from sase.main.plan_approve_handler import is_auto_approve_active
    from sase.question_shell import (
        create_question_gate_shell,
        question_base_prompt,
        question_rounds,
        resolve_question_chain_parent,
    )

    base_meta = _interrupted_phase_meta(state.current_artifacts_dir, ctx.agent_meta)
    meta_name = base_meta.get("name")
    creator_agent = (
        meta_name
        if isinstance(meta_name, str) and meta_name
        else (ctx.agent_name or "")
    )
    meta_family = base_meta.get("agent_family")
    lane = (
        meta_family
        if isinstance(meta_family, str) and meta_family
        else agent_family_base(creator_agent) or creator_agent
    )

    parent_artifacts_dir = resolve_question_chain_parent(
        ctx.project_name,
        lane,
        creator_agent,
        hint=state.question_gate_artifacts_dir,
    )
    if parent_artifacts_dir is not None:
        base_prompt = (
            question_base_prompt(parent_artifacts_dir) or state.question_base_prompt
        )
        prior_rounds = question_rounds(parent_artifacts_dir)
    else:
        base_prompt = state.question_base_prompt
        prior_rounds = []

    session_id = str(uuid.uuid4())
    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    agent_root_timestamp = os.environ.get("SASE_AGENT_ROOT_TIMESTAMP")
    action_data = {
        key: value
        for key, value in {
            "session_id": session_id,
            "agent_cl_name": agent_cl_name,
            "agent_project_file": agent_project_file,
            "agent_timestamp": agent_timestamp,
            "agent_root_timestamp": agent_root_timestamp,
        }.items()
        if value
    }

    creation = create_question_gate_shell(
        q_data.get("questions", []),
        session_id=session_id,
        producer={
            "agent": os.environ.get("SASE_AGENT"),
            "artifacts_dir": state.current_artifacts_dir,
            **action_data,
        },
        action_data=action_data,
        auto=is_auto_approve_active(),
        base_prompt=base_prompt,
        prior_rounds=prior_rounds,
        parent_artifacts_dir=parent_artifacts_dir,
        sdd_spec_path=state.sdd_spec_path,
    )

    question_relationships = {
        "questions_submitted_at": datetime.now(UTC).isoformat(),
        "question_request_path": str(creation.gate.request_path),
        "question_response_path": str(creation.gate.response_path),
        "question_session_id": session_id,
        "patch_name": ctx.cl_name,
        "changespec_name": ctx.cl_name,
    }
    record_workflow_metadata(state.current_artifacts_dir, question_relationships)
    state.question_gate_artifacts_dir = creation.record.artifacts_dir

    if not creation.should_handoff:
        _continue_after_auto_answered_question(
            ctx,
            state,
            creation,
            base_meta=base_meta,
            base_prompt=base_prompt,
            question_relationships=question_relationships,
        )
        return None

    from sase.axe.run_agent_exec_gate import handle_gate_marker

    gate_data = {
        "gate_id": creation.record.gate_id,
        "member_artifacts_dir": creation.record.artifacts_dir,
        "member_agent_name": creation.record.member_agent_name,
        "kind": "question",
    }
    return handle_gate_marker(gate_data, ctx, state)


def _continue_after_auto_answered_question(
    ctx: AgentExecContext,
    state: LoopState,
    creation: Any,
    *,
    base_meta: dict[str, Any],
    base_prompt: str,
    question_relationships: dict[str, Any],
) -> None:
    """Continue in-process after the ``%auto`` short-circuit answered a question.

    Mirrors the Off branch's ordinary successor launch -- suffix allocation,
    inherited role, relationships, and artifact-label arguments -- except the
    merged Q&A comes from the family's settled question gate shells, rebuilt
    here to include the round the gate shell just settled, rather than from
    ``LoopState.qa_rounds``.
    """
    from sase.question_shell import question_rounds

    rounds = question_rounds(creation.record.artifacts_dir)
    merged_qa_text = merge_qa_for_prompt(rounds)

    interrupted_suffix, interrupted_role = _question_interrupted_suffix_and_role(
        state,
        base_meta,
    )

    from sase.history.chat import save_chat_history
    from sase.history.chat_extras import format_extra_sections

    _q_suffix = interrupted_suffix
    _q_agent = agent_name_for_suffix(ctx, _q_suffix)
    _q_extra = format_extra_sections(state.current_artifacts_dir)

    _q_chat = save_chat_history(
        prompt=state.current_prompt,
        response=merged_qa_text,
        workflow="ace-run",
        agent=_q_agent,
        timestamp=ctx.timestamp,
        extra_sections=_q_extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=_q_agent,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
    )
    state.saved_chat_paths.append((_q_suffix, _q_chat))
    update_meta_field(state.current_artifacts_dir, "chat_path", _q_chat)
    update_step_marker_chat_path(state.current_artifacts_dir, _q_chat)

    reserved_suffixes = (
        *(suffix for suffix, _path in state.saved_chat_paths if suffix),
        interrupted_suffix,
    )
    suffix_template = f"{AGENT_FAMILY_SEPARATOR}@"
    followup_role = interrupted_role
    fallback_token = _question_successor_fallback_token(reserved_suffixes)
    followup_prompt = assemble_question_followup_prompt(base_prompt, rounds)
    continue_as_successor(
        ctx,
        state,
        SuccessorRequest(
            base_meta=base_meta,
            prompt=followup_prompt,
            suffix_template=suffix_template,
            extra_reserved_suffixes=reserved_suffixes,
            agent_family_role=followup_role,
            relationships={
                **question_relationships,
                "source_plan_agent_name": _q_agent,
            },
            prompt_artifact_label="Full question prompt",
            promote_role_suffix=interrupted_suffix,
            fallback_token=fallback_token,
        ),
        create_artifacts=create_followup_artifacts,
        promote=promote_to_workflow,
        store_prompt=_store_followup_prompt_artifact,
    )
    return None  # continue loop
