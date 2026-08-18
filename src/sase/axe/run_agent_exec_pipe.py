"""Pipe marker handling for the agent execution loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_exec_plan_accept_models import (
    resolve_model_alias_provenance,
    resolve_model_meta,
)
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_step_marker_chat_path,
)
from sase.axe.run_agent_successor import (
    FollowupModel,
    SuccessorRequest,
    continue_as_successor,
)
from sase.axe.runner_signals import reset_killed
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.config import (
    format_model_directive_value,
    normalize_model_alias_reference,
)
from sase.plan_chain import (
    allocate_agent_family_child_suffix,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_store_followup_prompt_artifact = store_followup_prompt_artifact


def handle_pipe_marker(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Adopt a ``.sase_pipe_pending`` marker after runner SIGTERM.

    Returns ``None`` so the execution loop runs the successor.
    """
    parent_dir = state.current_artifacts_dir
    normalize_handoff_interruption_state(parent_dir)
    finalize_handoff_artifacts_as_completed(parent_dir)
    base_meta = _interrupted_phase_meta(parent_dir, ctx.agent_meta)
    parent_name = _text(base_meta.get("name")) or ctx.agent_name
    name_token = _text(pipe_data.get("name_token"))
    fresh = bool(pipe_data.get("fresh"))
    reason = _text(pipe_data.get("reason"))
    model_spec = _text(pipe_data.get("model"))
    piped_prompt = pipe_data.get("prompt")
    if not isinstance(piped_prompt, str):
        piped_prompt = ""
    current_depth = _pipe_depth(pipe_data, base_meta)

    if name_token:
        suffix = f"--{name_token}"
        family_role = name_token
    elif ctx.agent_name:
        suffix = allocate_agent_family_child_suffix(
            ctx.agent_name,
            "--@",
            extra_reserved_suffixes=tuple(
                saved_suffix
                for saved_suffix, _path in state.saved_chat_paths
                if saved_suffix
            ),
        )
        family_role = "feedback"
    else:
        from sase.agent.names import render_agent_name_template

        suffix = render_agent_name_template("--@", "0")
        family_role = "feedback"

    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )

    extra = format_extra_sections(parent_dir)
    chat_path = save_chat_history(
        prompt=state.current_prompt,
        response=_format_pipe_response(
            successor_name=successor_name,
            reason=reason,
            piped_prompt=piped_prompt,
        ),
        workflow="ace-run",
        agent=parent_name,
        timestamp=ctx.timestamp,
        extra_sections=extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=parent_name,
        metadata_model=ctx.agent_model,
        metadata_llm_provider=ctx.agent_llm_provider,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
    )
    state.saved_chat_paths.append((state.current_role_suffix, chat_path))
    update_meta_field(parent_dir, "chat_path", chat_path)
    update_step_marker_chat_path(parent_dir, chat_path)

    followup_model = _resolve_pipe_model(model_spec) if model_spec else None
    successor_prompt = _build_pipe_successor_prompt(
        piped_prompt,
        parent_name=parent_name,
        fresh=fresh,
        model_prefix=followup_model.model_prefix if followup_model else "",
    )
    continue_as_successor(
        ctx,
        state,
        SuccessorRequest(
            base_meta=base_meta,
            prompt=successor_prompt,
            suffix=suffix,
            extra_reserved_suffixes=tuple(
                saved_suffix
                for saved_suffix, _path in state.saved_chat_paths
                if saved_suffix
            ),
            agent_family_role=family_role,
            relationships={
                "piped_from": parent_name,
                "pipe_reason": reason,
                "pipe_depth": current_depth + 1,
                "patch_name": ctx.cl_name,
                "changespec_name": ctx.cl_name,
            },
            prompt_artifact_label="Piped prompt",
            model=followup_model,
        ),
        create_artifacts=create_followup_artifacts,
        promote=promote_to_workflow,
        store_prompt=_store_followup_prompt_artifact,
    )
    state.question_base_prompt = state.current_prompt
    reset_killed()
    return None


def _build_pipe_successor_prompt(
    piped_prompt: str,
    *,
    parent_name: str | None,
    fresh: bool,
    model_prefix: str = "",
) -> str:
    """Assemble the successor prompt: model, optional fork, then piped text."""
    parts: list[str] = []
    if model_prefix:
        prefix = model_prefix if model_prefix.endswith("\n") else f"{model_prefix}\n"
        parts.append(prefix)
    if not fresh and parent_name:
        parts.append(f"#fork:{parent_name}\n")
    parts.append(piped_prompt)
    return "".join(parts)


def _resolve_pipe_model(model_spec: str) -> FollowupModel:
    directive = format_model_directive_value(model_spec)
    model_alias, _ = normalize_model_alias_reference(directive)
    trail, origin = resolve_model_alias_provenance(directive)
    return FollowupModel(
        model_prefix=f"%model:{directive}\n",
        meta=resolve_model_meta(directive),
        model_alias=model_alias,
        model_alias_trail=trail,
        model_alias_origin=origin,
    )


def _format_pipe_response(
    *,
    successor_name: str,
    reason: str | None,
    piped_prompt: str,
) -> str:
    lines = [
        "# Pipe hand-off",
        "",
        "This agent handed the remaining work to its next family member.",
        f"Successor: {successor_name}",
    ]
    if reason:
        lines.extend(["", "Reason:", "", reason])
    if piped_prompt:
        lines.extend(["", "Piped prompt:", "", piped_prompt])
    return "\n".join(lines).rstrip() + "\n"


def _interrupted_phase_meta(
    artifacts_dir: str,
    fallback_meta: dict[str, Any],
) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback_meta
    return loaded if isinstance(loaded, dict) and loaded else fallback_meta


def _pipe_depth(pipe_data: dict[str, Any], base_meta: dict[str, Any]) -> int:
    for source in (pipe_data, base_meta):
        raw = source.get("pipe_depth")
        if type(raw) is int and raw >= 0:
            return raw
    return 0


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "handle_pipe_marker",
]
