"""Build and create plan gate shells."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.gate_shell.store import list_gate_shells
from sase.gate_shell.transaction import GateShellCreation, create_gate_shell
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.plan_gate import PlanGateTier

_PLAN_ORIGINAL_PROMPT_FILENAME = "plan_shell_original_prompt.md"
_PLAN_CURRENT_PROMPT_FILENAME = "plan_shell_current_prompt.md"
_PLAN_QA_ROUNDS_FILENAME = "plan_shell_qa_rounds.json"


def plan_gate_shell_block(tier: PlanGateTier) -> dict[str, Any]:
    """Return the additive shell block for the trusted plan gate contract."""
    if tier == "epic":
        return {
            "pending_status": "EPIC",
            "settled_status": "EPIC APPROVED",
            "accent": "#D787FF",
            "workspace": "inherit",
            "next": {"fork": "family", "output": ["results"], "prompt": None},
            "branches": {
                "approve": {
                    "status": "EPIC APPROVED",
                    "accent": "#5FD7AF",
                    "prompt": None,
                    "fork": "none",
                },
                "reject": _terminal_branch("EPIC REJECTED", "#FF5F5F"),
                "feedback": _feedback_branch("#FF5FD7"),
                "timeout": _terminal_branch("EPIC TIMED OUT", "#FFAF00"),
                "stopped": _terminal_branch("EPIC CANCELLED", "#FFAF00"),
                "failed": _terminal_branch("EPIC FAILED", "#FF5F5F"),
            },
        }
    return {
        "pending_status": "TALE",
        "settled_status": "TALE APPROVED",
        "accent": "#FF87AF",
        "workspace": "inherit",
        "next": {"fork": "family", "output": ["results"], "prompt": None},
        "branches": {
            "approve+commit": _coder_branch("TALE APPROVED", "#00D7D7"),
            "approve": _coder_branch("PLAN APPROVED", "#00D7AF"),
            "commit": _terminal_branch("PLAN COMMITTED", "#5FD75F"),
            "reject": _terminal_branch("PLAN REJECTED", "#D7AF5F"),
            "feedback": _feedback_branch("#FF5FD7"),
            "timeout": _terminal_branch("PLAN TIMED OUT", "#FFAF00"),
            "stopped": _terminal_branch("PLAN CANCELLED", "#FFAF00"),
            "failed": _terminal_branch("PLAN FAILED", "#FF5F5F"),
        },
    }


def create_plan_gate_shell(
    plan_file: str,
    *,
    session_id: str,
    ctx: AgentExecContext,
    state: LoopState,
    agent_runtime: str | None,
) -> GateShellCreation:
    """Create a shell-backed plan gate and persist settlement context."""
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    auto_action = get_auto_plan_approval_action()
    auto_enabled = auto_action is not None
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action

    from sase.plan_gate import build_plan_approval_gate_spec

    spec = build_plan_approval_gate_spec(
        plan_file,
        session_id,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
        agent_name=ctx.agent_name,
        agent_model=ctx.agent_model,
        agent_llm_provider=ctx.agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=ctx.vcs_tag,
    )
    tier: PlanGateTier = "epic" if spec["kind"] == "epic_plan" else "tale"
    spec["shell"] = plan_gate_shell_block(tier)

    source_role_suffix = state.current_role_suffix or PLAN_CHAIN_PLAN_SUFFIX
    source_plan_agent_name = _agent_name_for_suffix(ctx.agent_name, source_role_suffix)
    source_meta = _read_meta(state.current_artifacts_dir)
    lane = _plan_lane(source_meta, source_plan_agent_name, ctx.agent_name)
    parent_artifacts_dir = _resolve_plan_shell_parent(
        ctx.project_name,
        lane,
        source_plan_agent_name or ctx.agent_name or "",
        hint=state.plan_gate_artifacts_dir,
    )

    def _record_context(record: Any, _gate: Any) -> None:
        _write_shell_context(
            record.artifacts_dir,
            tier=tier,
            plan_file=plan_file,
            session_id=session_id,
            ctx=ctx,
            state=state,
            source_role_suffix=source_role_suffix,
            source_plan_agent_name=source_plan_agent_name,
            parent_artifacts_dir=parent_artifacts_dir,
        )

    creation = create_gate_shell(spec, before_auto_settle=_record_context)
    _write_shell_context(
        creation.record.artifacts_dir,
        tier=tier,
        plan_file=plan_file,
        session_id=session_id,
        ctx=ctx,
        state=state,
        source_role_suffix=source_role_suffix,
        source_plan_agent_name=source_plan_agent_name,
        parent_artifacts_dir=parent_artifacts_dir,
    )

    if auto_enabled:
        from sase.llm_provider._plan_utils import mark_auto_approved_plan_handled

        mark_auto_approved_plan_handled(
            plan_file,
            ctx.agent_name,
            action=auto_action,
        )

    if creation.gate.notification_id is not None:
        from sase.main.plan_approve_handler import (
            get_tmux_prefix,
            send_desktop_notification,
        )

        prefix = get_tmux_prefix()
        send_desktop_notification(
            f"{prefix} Plan Complete", "Plan ready for review in sase ace"
        )

    return creation


def _resolve_plan_shell_parent(
    project_name: str,
    lane: str,
    creator_agent: str,
    *,
    hint: str | None,
) -> str | None:
    """Return the previous plan gate shell in this replan chain, if any."""
    if hint:
        hint_meta = _read_meta(hint)
        if (
            hint_meta.get("gate_kind") in {"plan", "epic_plan"}
            and hint_meta.get("agent_family") == lane
        ):
            return hint

    candidates = sorted(
        (
            record
            for record in list_gate_shells(project=project_name)
            if record.lane == lane
            and record.kind in {"plan", "epic_plan"}
            and record.is_terminal
            and record.followup_agent == creator_agent
        ),
        key=lambda record: record.timestamp,
        reverse=True,
    )
    return candidates[0].artifacts_dir if candidates else None


def _coder_branch(status: str, accent: str) -> dict[str, Any]:
    return {
        "status": status,
        "accent": accent,
        "prompt": "Implement the approved plan.",
        "output": ["results"],
        "fork": "none",
        "suffix": PLAN_CHAIN_CODER_SUFFIX,
        "role": "code",
        "raw_prompt": True,
    }


def _feedback_branch(accent: str) -> dict[str, Any]:
    return {
        "status": "FEEDBACK",
        "accent": accent,
        "prompt": "Revise the plan using the reviewer feedback.",
        "output": ["results"],
        "fork": "family",
        "suffix": f"{PLAN_CHAIN_PLAN_SUFFIX}-@",
        "role": "feedback",
        "raw_prompt": True,
    }


def _terminal_branch(status: str, accent: str) -> dict[str, Any]:
    return {"status": status, "accent": accent, "prompt": None, "fork": "none"}


def _write_shell_context(
    artifacts_dir: str,
    *,
    tier: PlanGateTier,
    plan_file: str,
    session_id: str,
    ctx: AgentExecContext,
    state: LoopState,
    source_role_suffix: str,
    source_plan_agent_name: str | None,
    parent_artifacts_dir: str | None,
) -> None:
    fields: dict[str, Any] = {
        "plan_shell_tier": tier,
        "plan_shell_session_id": session_id,
        "plan_shell_plan_path": plan_file,
        "plan_shell_source_artifacts_dir": state.current_artifacts_dir,
        "plan_shell_source_role_suffix": source_role_suffix,
        "plan_shell_source_plan_agent_name": source_plan_agent_name,
        "plan_shell_agent_name": ctx.agent_name,
        "plan_shell_project_name": ctx.project_name,
        "plan_shell_project_file": ctx.project_file,
        "plan_shell_workspace_dir": ctx.workspace_dir,
        "plan_shell_workspace_num": ctx.workspace_num,
        "plan_shell_output_path": ctx.output_path,
        "plan_shell_timestamp": ctx.timestamp,
        "plan_shell_artifacts_timestamp": ctx.artifacts_timestamp,
        "plan_shell_vcs_tag": ctx.vcs_tag,
        "plan_shell_agent_model": ctx.agent_model,
        "plan_shell_agent_llm_provider": ctx.agent_llm_provider,
        "plan_shell_agent_vcs_provider": ctx.agent_vcs_provider,
        "plan_shell_multi_agent_prompt_file": ctx.multi_agent_prompt_file,
        "plan_shell_is_home_mode": ctx.is_home_mode,
        "plan_shell_feedback_round": state.feedback_round,
        "plan_shell_agent_meta": _json_safe_mapping(ctx.agent_meta),
        "patch_name": ctx.cl_name,
        "changespec_name": ctx.cl_name,
    }
    if state.sdd_spec_path:
        fields["plan_shell_sdd_spec_path"] = state.sdd_spec_path
    if parent_artifacts_dir is not None:
        fields["plan_shell_prev_artifacts_dir"] = parent_artifacts_dir

    original_prompt_path = _inherited_prompt_path(
        parent_artifacts_dir,
        "plan_shell_original_prompt_path",
    )
    if original_prompt_path is None:
        original_prompt_path = str(Path(artifacts_dir) / _PLAN_ORIGINAL_PROMPT_FILENAME)
        Path(original_prompt_path).write_text(state.original_prompt, encoding="utf-8")
    fields["plan_shell_original_prompt_path"] = original_prompt_path

    current_prompt_path = str(Path(artifacts_dir) / _PLAN_CURRENT_PROMPT_FILENAME)
    Path(current_prompt_path).write_text(state.current_prompt, encoding="utf-8")
    fields["plan_shell_current_prompt_path"] = current_prompt_path

    qa_rounds_path = str(Path(artifacts_dir) / _PLAN_QA_ROUNDS_FILENAME)
    Path(qa_rounds_path).write_text(
        json.dumps([_qa_round_to_json(round_) for round_ in state.qa_rounds], indent=2)
        + "\n",
        encoding="utf-8",
    )
    fields["plan_shell_qa_rounds_path"] = qa_rounds_path

    update_meta_fields(artifacts_dir, fields)


def _inherited_prompt_path(
    parent_artifacts_dir: str | None,
    key: str,
) -> str | None:
    if parent_artifacts_dir is None:
        return None
    value = _read_meta(parent_artifacts_dir).get(key)
    return value if isinstance(value, str) and value else None


def _qa_round_to_json(round_: Any) -> dict[str, Any]:
    return {
        "questions": list(getattr(round_, "questions", []) or []),
        "answers": list(getattr(round_, "answers", []) or []),
        "global_note": getattr(round_, "global_note", None),
    }


def _json_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        try:
            json.dumps(item)
        except TypeError:
            continue
        safe[key] = item
    return safe


def _plan_lane(
    source_meta: Mapping[str, Any],
    source_plan_agent_name: str | None,
    agent_name: str | None,
) -> str:
    raw_family = source_meta.get("agent_family")
    if isinstance(raw_family, str) and raw_family:
        return raw_family
    for candidate in (source_plan_agent_name, agent_name):
        lane = agent_family_base(candidate) if candidate else None
        if lane:
            return lane
        if candidate:
            return candidate
    return ""


def _agent_name_for_suffix(agent_name: str | None, suffix: str | None) -> str | None:
    if not agent_name or not suffix:
        return None
    from sase.plan_chain import plan_chain_agent_name

    return plan_chain_agent_name(agent_name, suffix)


def _read_meta(artifacts_dir: str) -> dict[str, Any]:
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


__all__ = [
    "create_plan_gate_shell",
    "plan_gate_shell_block",
]
