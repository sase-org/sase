"""Frozen approval inputs for staged plan and question handoffs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
from typing import Any

from sase.core.atomic_json import write_json_marker_atomic
from sase.agent._staged_handoff_store import (
    StagedHandoffError,
    artifacts_root,
    path_exists,
    read_json_object,
)

STAGED_APPROVAL_CONTEXT_FILENAME = ".sase_handoff_approval.json"


def _read_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    try:
        value = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _plan_auto_snapshot(meta: Mapping[str, Any]) -> tuple[str | None, str | None, Any]:
    from sase.autonomy.record import read_record

    argument = meta.get("auto_approve_argument")
    policy = read_record(meta)
    action: str | None = None
    if isinstance(argument, str):
        normalized = argument.strip().lower()
        action = normalized if normalized in {"epic", "tale"} else "approve"
        argument = argument.strip() or None
    elif policy is not None:
        selection = policy.get("selection")
        if selection in {"epic", "tale"}:
            action = selection
            argument = selection
        elif policy.get("profile") != "manual":
            action = "approve"
            argument = selection if selection in {"plan", "epic", "tale"} else None
    else:
        raw_action = meta.get("auto_approve_plan_action")
        if isinstance(raw_action, str) and raw_action.strip().lower() in {
            "approve",
            "epic",
            "tale",
        }:
            action = raw_action.strip().lower()
        elif meta.get("approve"):
            action = "approve"
    return action, argument if isinstance(argument, str) else None, policy


def _question_auto_snapshot(meta: Mapping[str, Any]) -> tuple[bool, Any]:
    from sase.autonomy.record import read_record

    policy = read_record(meta)
    raw_argument = meta.get("auto_approve_argument")
    enabled = (
        isinstance(raw_argument, str)
        or (policy is not None and policy.get("profile") != "manual")
        or (policy is None and bool(meta.get("approve")))
    )
    return enabled, policy


def _qa_round_json(round_: Any) -> dict[str, Any]:
    return {
        "questions": list(getattr(round_, "questions", []) or []),
        "answers": list(getattr(round_, "answers", []) or []),
        "global_note": getattr(round_, "global_note", None),
    }


def _question_parent(
    continuation: Any,
    run_metadata: Mapping[str, Any],
) -> str | None:
    state = continuation.state
    hinted = state.question_gate_artifacts_dir or run_metadata.get(
        "question_gate_artifacts_dir"
    )
    if isinstance(hinted, str) and hinted.strip():
        return hinted.strip()
    ctx = continuation.ctx
    from sase.plan_chain import agent_session_base, agent_session_value
    from sase.question_gate_turn import resolve_question_chain_parent

    creator = run_metadata.get("name") or ctx.agent_name or ""
    lane = (
        agent_session_value(run_metadata) or agent_session_base(str(creator)) or creator
    )
    return resolve_question_chain_parent(
        ctx.project_name,
        str(lane),
        str(creator),
        hint=None,
    )


def _creator_context(
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: Any,
) -> dict[str, Any]:
    ctx = continuation.ctx
    state = continuation.state
    agent = run_metadata.get("name") or ctx.agent_name
    model = run_metadata.get("model") or ctx.agent_model
    provider = run_metadata.get("llm_provider") or ctx.agent_llm_provider
    project_dir: str | None = None
    try:
        from sase.env_contracts import provider_project_dir_from_env

        project_dir = provider_project_dir_from_env()
    except Exception:
        project_dir = None
    if not project_dir and isinstance(ctx.project_file, str) and ctx.project_file:
        project_dir = str(Path(ctx.project_file).parent)

    from sase.axe.run_agent_runtime import format_agent_run_runtime

    runtime = format_agent_run_runtime(
        launch_timestamp_suffix=ctx.artifacts_timestamp,
        run_started_at=(
            run_metadata.get("run_started_at")
            if isinstance(run_metadata.get("run_started_at"), str)
            else None
        ),
        completion_time=datetime.now(UTC),
    )
    values: dict[str, Any] = {
        "agent": os.environ.get("SASE_AGENT") or agent,
        "agent_name": agent,
        "agent_model": model,
        "agent_llm_provider": provider,
        "agent_runtime": runtime,
        "agent_vcs_tag": run_metadata.get("vcs_tag") or ctx.vcs_tag,
        "artifacts_dir": artifacts_dir,
        "project_dir": project_dir,
        "agent_cl_name": os.environ.get("SASE_AGENT_CL_NAME") or ctx.cl_name,
        "agent_project_file": os.environ.get("SASE_AGENT_PROJECT_FILE")
        or ctx.project_file,
        "agent_timestamp": os.environ.get("SASE_AGENT_TIMESTAMP") or ctx.timestamp,
        "agent_root_timestamp": os.environ.get("SASE_AGENT_ROOT_TIMESTAMP")
        or state.original_agent_timestamp
        or ctx.timestamp,
    }
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, (str, int, float, bool)) and value != ""
    }


def _build_approval_context(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: Any,
) -> dict[str, Any]:
    staged_id = staged_record.get("staged_id")
    kind = staged_record.get("kind")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("staged approval context has no staged_id")
    if kind not in {"plan", "questions"}:
        raise StagedHandoffError("staged approval context has an unsupported kind")

    ctx = continuation.ctx
    state = continuation.state
    meta = _read_agent_meta(artifacts_dir)
    if run_metadata:
        meta = dict(run_metadata)
    plan_action, plan_argument, policy = _plan_auto_snapshot(meta)
    question_auto, question_policy = _question_auto_snapshot(meta)
    creator = _creator_context(artifacts_dir, meta, continuation)
    question_context: dict[str, Any] = {}
    serialized_rounds = [_qa_round_json(round_) for round_ in state.qa_rounds]
    if kind == "questions":
        parent = _question_parent(continuation, meta)
        base_prompt = state.question_base_prompt
        prior_rounds: list[Any] = []
        if parent:
            from sase.question_gate_turn import (
                question_base_authored_request,
                question_base_prompt,
                question_rounds,
            )

            base_prompt = question_base_prompt(parent) or base_prompt
            state.question_base_authored_request = (
                question_base_authored_request(parent)
                or state.question_base_authored_request
            )
            prior_rounds = question_rounds(parent)
        question_context = {
            "parent_artifacts_dir": parent,
            "base_prompt": base_prompt,
            "base_authored_request": state.question_base_authored_request,
            "prior_rounds": [_qa_round_json(round_) for round_ in prior_rounds],
            "sdd_spec_path": state.sdd_spec_path,
        }

    return {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": kind,
        "session_id": staged_id,
        "request_timestamp": time.time(),
        "creator": creator,
        "plan": {
            "auto_action": plan_action,
            "auto_argument": plan_argument,
            "auto_policy": policy,
            "feedback_round": state.feedback_round,
        },
        "questions": {
            "auto_enabled": question_auto,
            "auto_policy": question_policy,
            **question_context,
        },
        "execution": {
            "current_prompt": state.current_prompt,
            "original_prompt": state.original_prompt,
            "question_base_prompt": state.question_base_prompt,
            "authored_local_request": state.authored_local_request,
            "initial_authored_local_request": state.initial_authored_local_request,
            "question_base_authored_request": state.question_base_authored_request,
            "qa_rounds": serialized_rounds,
            "feedback_round": state.feedback_round,
            "feedback_bullets": list(state.feedback_bullets),
            "current_role_suffix": state.current_role_suffix,
            "sdd_spec_path": state.sdd_spec_path,
            "question_gate_artifacts_dir": state.question_gate_artifacts_dir,
            "plan_gate_artifacts_dir": state.plan_gate_artifacts_dir,
            "saved_chat_paths": [list(item) for item in state.saved_chat_paths],
            "agent_name": ctx.agent_name,
            "project_name": ctx.project_name,
            "project_file": ctx.project_file,
            "workspace_dir": ctx.workspace_dir,
            "workspace_num": ctx.workspace_num,
            "cl_name": ctx.cl_name,
            "output_path": ctx.output_path,
            "update_target": ctx.update_target,
            "is_home_mode": ctx.is_home_mode,
            "artifacts_dir": ctx.artifacts_dir,
            "agent_hidden": ctx.agent_hidden,
            "timestamp": ctx.timestamp,
            "artifacts_timestamp": ctx.artifacts_timestamp,
            "agent_model": ctx.agent_model,
            "agent_llm_provider": ctx.agent_llm_provider,
            "agent_vcs_provider": ctx.agent_vcs_provider,
            "vcs_tag": ctx.vcs_tag,
            "multi_agent_prompt_file": ctx.multi_agent_prompt_file,
            "workflow_name": ctx.workflow_name,
        },
    }


def _validate_approval_context(
    value: Mapping[str, Any], *, staged_id: str, kind: str
) -> dict[str, Any]:
    if (
        value.get("schema_version") != 1
        or value.get("staged_id") != staged_id
        or value.get("kind") != kind
        or value.get("session_id") != staged_id
        or not isinstance(value.get("request_timestamp"), (int, float))
        or not isinstance(value.get("creator"), Mapping)
        or not isinstance(value.get("plan"), Mapping)
        or not isinstance(value.get("questions"), Mapping)
        or not isinstance(value.get("execution"), Mapping)
    ):
        raise StagedHandoffError("staged approval context is malformed or mismatched")
    return dict(value)


def _read_staged_approval_context(
    artifacts_dir: str | None = None,
    *,
    staged_id: str,
    kind: str,
) -> dict[str, Any] | None:
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_APPROVAL_CONTEXT_FILENAME
    if not path_exists(path):
        return None
    payload = read_json_object(path, label="staged approval context")
    return _validate_approval_context(payload, staged_id=staged_id, kind=kind)


def ensure_staged_approval_context_locked(
    staged_record: Mapping[str, Any],
    *,
    artifacts_dir: str,
    run_metadata: Mapping[str, Any],
    continuation: Any,
) -> dict[str, Any]:
    """Freeze the approval request before its first gate or successor side effect.

    Callers hold the staged adoption lock. Once written, retries use this
    original creator, policy, request identity, and prompt/round snapshot.
    """
    staged_id = str(staged_record.get("staged_id") or "")
    kind = str(staged_record.get("kind") or "")
    existing = _read_staged_approval_context(
        artifacts_dir, staged_id=staged_id, kind=kind
    )
    if existing is not None:
        return existing
    context = _build_approval_context(
        staged_record,
        artifacts_dir=artifacts_dir,
        run_metadata=run_metadata,
        continuation=continuation,
    )
    normalized = _validate_approval_context(context, staged_id=staged_id, kind=kind)
    write_json_marker_atomic(
        Path(artifacts_dir) / STAGED_APPROVAL_CONTEXT_FILENAME, normalized
    )
    return normalized


def restore_staged_approval_loop_state(state: Any, context: Mapping[str, Any]) -> None:
    """Reapply the exact prompt and feedback inputs frozen for this stage."""
    execution = context.get("execution")
    if not isinstance(execution, Mapping):
        raise StagedHandoffError("staged approval execution context is malformed")
    for key in (
        "current_prompt",
        "original_prompt",
        "question_base_prompt",
        "authored_local_request",
        "initial_authored_local_request",
        "question_base_authored_request",
        "current_role_suffix",
        "sdd_spec_path",
        "question_gate_artifacts_dir",
        "plan_gate_artifacts_dir",
    ):
        value = execution.get(key)
        if value is None or isinstance(value, str):
            setattr(state, key, value)
    raw_rounds = execution.get("qa_rounds")
    if isinstance(raw_rounds, list):
        from sase.main.qa_markdown import QARound

        rounds: list[QARound] = []
        for item in raw_rounds:
            if not isinstance(item, Mapping):
                continue
            questions = item.get("questions")
            answers = item.get("answers")
            if isinstance(questions, list) and isinstance(answers, list):
                note = item.get("global_note")
                rounds.append(
                    QARound(
                        questions=questions,
                        answers=answers,
                        global_note=note if isinstance(note, str) else None,
                    )
                )
        state.qa_rounds = rounds
    bullets = execution.get("feedback_bullets")
    if isinstance(bullets, list):
        state.feedback_bullets = [item for item in bullets if isinstance(item, str)]
    feedback_round = execution.get("feedback_round")
    if type(feedback_round) is int:
        state.feedback_round = feedback_round
    chats = execution.get("saved_chat_paths")
    if isinstance(chats, list):
        state.saved_chat_paths = [
            (item[0], item[1])
            for item in chats
            if isinstance(item, list)
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
        ]


__all__ = [
    "STAGED_APPROVAL_CONTEXT_FILENAME",
    "ensure_staged_approval_context_locked",
    "restore_staged_approval_loop_state",
]
