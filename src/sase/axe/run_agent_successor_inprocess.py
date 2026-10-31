"""Ordinary in-process successor continuation."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe._run_agent_successor_shared import resolved_suffix
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
)
from sase.axe.run_agent_successor_model import write_followup_model_meta
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.plan_chain import plan_chain_agent_name

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.axe.run_agent_successor_types import SuccessorRequest


def _explicit_autonomy_selection(prompt: str) -> str | None:
    """Extract the agent-authored ``%auto`` selection from a successor prompt.

    Returns ``""`` for bare ``%auto``, the argument for enabled spellings,
    ``"manual"`` for explicit ``:manual``/``:off``, and None when the prompt
    carries no ``%auto``. Invalid spellings fail closed to None (pure
    inherit); Python only extracts and transports, core decides narrowing.
    """
    try:
        from sase.macro.directives import extract_prompt_directives
    except Exception:
        return None
    try:
        _, directives = extract_prompt_directives(prompt)
    except Exception:
        return None
    try:
        if directives.auto_enabled and directives.auto_argument is not None:
            return str(directives.auto_argument)
        if directives.auto_enabled:
            return ""
        if bool(getattr(directives, "auto_present", False)):
            return "manual"
    except Exception:
        return None
    return None


def continue_as_inprocess_successor(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    create_artifacts: Callable[..., str] | None = None,
    promote: Callable[..., None] | None = None,
    store_prompt: Callable[..., None] | None = None,
    write_model_meta: Callable[..., None] | None = None,
) -> str:
    """Run the ordinary in-process continuation after identity is chosen."""
    create = create_followup_artifacts if create_artifacts is None else create_artifacts
    promote_fn = promote_to_workflow if promote is None else promote
    store = store_followup_prompt_artifact if store_prompt is None else store_prompt
    write_model = (
        write_followup_model_meta if write_model_meta is None else write_model_meta
    )

    suffix = resolved_suffix(ctx, request)
    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )
    if request.before_state_change is not None:
        request.before_state_change(suffix, successor_name)

    mark_lifecycle_phase(state.current_artifacts_dir, "handoff")
    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        if request.promote_role_suffix is None:
            promote_fn(ctx.artifacts_dir, ctx.agent_name)
        else:
            promote_fn(
                ctx.artifacts_dir,
                ctx.agent_name,
                role_suffix=request.promote_role_suffix,
            )

    state.current_role_suffix = suffix
    if request.before_create is not None:
        request.before_create(suffix, successor_name)
    relationships = dict(request.relationships or {})
    explicit_selection = _explicit_autonomy_selection(request.prompt)
    if (
        explicit_selection is not None
        and "autonomy_explicit_selection" not in relationships
    ):
        relationships["autonomy_explicit_selection"] = explicit_selection
    create_kwargs: dict[str, Any] = {
        "workspace_num": ctx.workspace_num,
        "agent_name_override": successor_name if ctx.agent_name else None,
        "workflow_name": ctx.agent_name,
        "relationships": relationships,
        "prev_artifacts_dir": state.current_artifacts_dir,
    }
    if request.agent_session_role is not None:
        create_kwargs["agent_session_role"] = request.agent_session_role
    if request.reserved_timestamp is not None:
        create_kwargs["timestamp"] = request.reserved_timestamp
    state.current_artifacts_dir = create(
        ctx.project_name,
        request.base_meta,
        suffix,
        convert_timestamp_to_artifacts_format(ctx.timestamp),
        **create_kwargs,
    )
    if request.model is not None:
        write_model(state, request.model)
    state.current_prompt = request.prompt
    store(
        state.current_artifacts_dir,
        state.current_prompt,
        label=request.prompt_artifact_label,
    )
    return successor_name


__all__ = ["continue_as_inprocess_successor"]
