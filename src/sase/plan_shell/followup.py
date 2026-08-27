"""Settle-time rebuild of plan gate-shell follow-up prompts."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.main.qa_markdown import QARound

_MAX_CHAIN_LINKS = 200


def plan_next_action(
    *,
    artifacts_dir: str,
    meta: dict[str, Any],
    envelope: dict[str, Any],
    response: dict[str, Any],
    declared: str | None,
) -> str | None:
    """Return the plan branch's exact follow-up prompt from durable state."""
    del envelope
    result = _plan_result_from_artifacts(
        artifacts_dir,
        response=response,
    )
    if result is None:
        return declared
    if result.action == "feedback":
        return _feedback_next_action(artifacts_dir, response, declared)
    if result.action == "approve" and result.run_coder:
        return _accepted_tale_next_action(artifacts_dir, meta, result)
    return None


def plan_result_from_gate_creation(creation: Any) -> Any | None:
    """Return the runner plan result for a shell gate creation."""
    response = _read_json_object(str(creation.gate.response_path))
    if response is None:
        return None
    from sase.llm_provider._plan_utils import plan_approval_result_from_gate_response

    return plan_approval_result_from_gate_response(
        creation.gate.bundle_path,
        response,
        auto_resolved=creation.gate.auto_resolution.get("state") == "resolved",
    )


def _plan_result_from_artifacts(
    artifacts_dir: str,
    *,
    response: dict[str, Any] | None = None,
) -> Any | None:
    """Project one plan-shell bundle response into ``PlanApprovalResult``."""
    meta = _read_meta(artifacts_dir)
    bundle_path = meta.get("gate_bundle_path")
    if not isinstance(bundle_path, str) or not bundle_path:
        return None
    bundle = Path(bundle_path)
    if response is None:
        response = _read_json_object(str(bundle / "response.json"))
    if response is None:
        return None
    from sase.llm_provider._plan_utils import plan_approval_result_from_gate_response

    return plan_approval_result_from_gate_response(bundle, response)


def _plan_feedback_bullets(
    head_artifacts_dir: str,
    *,
    head_response: dict[str, Any] | None = None,
) -> list[str]:
    """Return feedback bullets from this plan-shell chain, oldest first."""
    chain = _plan_shell_chain(head_artifacts_dir)
    bullets: list[str] = []
    for artifacts_dir in chain:
        is_head = artifacts_dir == chain[-1]
        result = _plan_result_from_artifacts(
            artifacts_dir,
            response=head_response if is_head else None,
        )
        feedback = getattr(result, "feedback", None)
        if getattr(result, "action", None) == "feedback" and isinstance(feedback, str):
            bullets.append(feedback)
    return bullets


def _plan_original_prompt(head_artifacts_dir: str) -> str:
    """Return the chain's original planner prompt, or ``""``."""
    chain = _plan_shell_chain(head_artifacts_dir)
    root = chain[0] if chain else head_artifacts_dir
    path = _read_meta(root).get("plan_shell_original_prompt_path")
    return _read_text(path)


def _plan_current_prompt(head_artifacts_dir: str) -> str:
    """Return the prompt used by this plan-shell's interrupted planner."""
    path = _read_meta(head_artifacts_dir).get("plan_shell_current_prompt_path")
    return _read_text(path)


def _plan_qa_rounds(head_artifacts_dir: str) -> list[QARound]:
    """Return the Q&A rounds recorded for this plan-shell chain."""
    for artifacts_dir in reversed(_plan_shell_chain(head_artifacts_dir)):
        path = _read_meta(artifacts_dir).get("plan_shell_qa_rounds_path")
        data = _read_json_array(path)
        if data is None:
            continue
        rounds = [_qa_round_from_json(item) for item in data]
        return [round_ for round_ in rounds if round_ is not None]
    return []


def _feedback_next_action(
    artifacts_dir: str,
    response: dict[str, Any],
    declared: str | None,
) -> str | None:
    original_prompt = _plan_original_prompt(artifacts_dir)
    feedback = _plan_feedback_bullets(artifacts_dir, head_response=response)
    if not original_prompt or not feedback:
        return declared
    from sase.axe.run_agent_helpers import assemble_feedback_replan_prompt

    return assemble_feedback_replan_prompt(
        original_prompt,
        feedback,
        _plan_qa_rounds(artifacts_dir),
    )


def _accepted_tale_next_action(
    artifacts_dir: str,
    meta: dict[str, Any],
    plan_result: Any,
) -> str | None:
    ctx, state = _rebuild_exec_inputs(artifacts_dir, meta)
    from sase.axe.run_agent_exec_plan import record_workflow_metadata
    from sase.axe.run_agent_exec_plan_accept import prepare_accepted_plan_successor

    prepared = prepare_accepted_plan_successor(plan_result, ctx, state)
    if prepared.successor is None:
        return None
    record_workflow_metadata(artifacts_dir, prepared.successor.relationships)
    return prepared.successor.prompt


def _rebuild_exec_inputs(
    artifacts_dir: str, meta: Mapping[str, Any]
) -> tuple[Any, Any]:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.plan_chain import PLAN_CHAIN_PLAN_SUFFIX, agent_family_base

    source_agent = _str(meta.get("plan_shell_source_plan_agent_name"))
    agent_name = _str(meta.get("plan_shell_agent_name"))
    if agent_name is None and source_agent:
        agent_name = agent_family_base(source_agent) or source_agent

    source_artifacts_dir = (
        _str(meta.get("plan_shell_source_artifacts_dir")) or artifacts_dir
    )
    source_role_suffix = (
        _str(meta.get("plan_shell_source_role_suffix")) or PLAN_CHAIN_PLAN_SUFFIX
    )
    agent_meta = meta.get("plan_shell_agent_meta")
    base_meta = dict(agent_meta) if isinstance(agent_meta, Mapping) else {}
    for key, source_key in (
        ("model", "plan_shell_agent_model"),
        ("llm_provider", "plan_shell_agent_llm_provider"),
        ("vcs_provider", "plan_shell_agent_vcs_provider"),
    ):
        value = meta.get(source_key)
        if isinstance(value, str) and value:
            base_meta.setdefault(key, value)

    ctx = AgentExecContext(
        cl_name=_str(meta.get("patch_name")) or _str(meta.get("changespec_name")) or "",
        project_file=_str(meta.get("plan_shell_project_file")) or "",
        workspace_dir=_str(meta.get("plan_shell_workspace_dir")) or os.getcwd(),
        output_path=_str(meta.get("plan_shell_output_path")) or "",
        workspace_num=_int(meta.get("plan_shell_workspace_num")) or 0,
        timestamp=_str(meta.get("plan_shell_timestamp")) or "",
        update_target="",
        project_name=_str(meta.get("plan_shell_project_name")) or "",
        is_home_mode=bool(meta.get("plan_shell_is_home_mode", False)),
        artifacts_dir=source_artifacts_dir,
        artifacts_timestamp=_str(meta.get("plan_shell_artifacts_timestamp")) or "",
        vcs_tag=_str(meta.get("plan_shell_vcs_tag")),
        agent_name=agent_name,
        agent_model=_str(meta.get("plan_shell_agent_model")),
        agent_llm_provider=_str(meta.get("plan_shell_agent_llm_provider")),
        agent_vcs_provider=_str(meta.get("plan_shell_agent_vcs_provider")),
        agent_hidden=False,
        agent_meta=base_meta,
        local_xprompts={},
        multi_agent_prompt_file=_str(meta.get("plan_shell_multi_agent_prompt_file")),
    )
    state = LoopState(
        current_prompt=_plan_current_prompt(artifacts_dir)
        or _plan_original_prompt(artifacts_dir),
        current_role_suffix=source_role_suffix,
        current_artifacts_dir=artifacts_dir,
        loop_outcome="",
        sdd_spec_path=_str(meta.get("plan_shell_sdd_spec_path")),
        original_prompt=_plan_original_prompt(artifacts_dir),
        qa_rounds=_plan_qa_rounds(artifacts_dir),
        feedback_bullets=_plan_feedback_bullets(artifacts_dir),
        feedback_round=_int(meta.get("plan_shell_feedback_round")) or 0,
    )
    return ctx, state


def _plan_shell_chain(head_artifacts_dir: str) -> tuple[str, ...]:
    chain: list[str] = []
    seen: set[str] = set()
    current: str | None = head_artifacts_dir
    while current is not None and current not in seen and len(chain) < _MAX_CHAIN_LINKS:
        chain.append(current)
        seen.add(current)
        prev = _read_meta(current).get("plan_shell_prev_artifacts_dir")
        current = prev if isinstance(prev, str) and prev else None
    chain.reverse()
    return tuple(chain)


def _qa_round_from_json(value: object) -> QARound | None:
    if not isinstance(value, Mapping):
        return None
    questions = value.get("questions")
    answers = value.get("answers")
    global_note = value.get("global_note")
    if not isinstance(questions, list) or not isinstance(answers, list):
        return None
    return QARound(
        questions=[item for item in questions if isinstance(item, dict)],
        answers=[item for item in answers if isinstance(item, dict)],
        global_note=global_note if isinstance(global_note, str) else None,
    )


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    return _read_json_object(os.path.join(artifacts_dir, "agent_meta.json")) or {}


def _read_json_object(path: str | Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _read_json_array(path: object) -> list[Any] | None:
    if not isinstance(path, str) or not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, list) else None


def _read_text(path: object) -> str:
    if not isinstance(path, str) or not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value:
        try:
            return int(value)
        except ValueError:
            return None
    return None


__all__ = [
    "plan_next_action",
    "plan_result_from_gate_creation",
]
