"""In-process family-successor engine for the agent execution loop.

Plan-approval coder hand-off and questions follow-up both become the next
family member with this six-step sequence. The order is load-bearing:

1. Bump ``state.agent_step`` and ``promote_to_workflow`` when the step
   reaches 2 and the agent is named. Promotion turns a lone agent into a
   family root and must happen before follow-up artifacts are created.
2. Resolve the successor suffix: ``request.suffix`` verbatim, otherwise
   ``allocate_agent_family_child_suffix`` on ``request.suffix_template``,
   otherwise an unnamed-agent template render (``fallback_token``).
3. Set ``state.current_role_suffix``, then ``create_followup_artifacts``
   with ``agent_name_override=plan_chain_agent_name(...)``.
4. Write follow-up model metadata when ``request.model`` is set.
5. Set ``state.current_prompt`` to the request prompt.
6. ``store_followup_prompt_artifact`` under ``request.prompt_artifact_label``.

Callers assemble the prompt, relationships, and (for questions) the
promote role-suffix. This module only sequences the hand-off.

Optional hook kwargs honor caller-module test doubles: plan-accept and
questions tests patch ``create_followup_artifacts``,
``promote_to_workflow``, ``_store_followup_prompt_artifact``, and
``_write_followup_model_meta`` on those modules.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_chain import (
    allocate_agent_family_child_suffix,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState

_PLAN_ACCEPT_MODULE = "sase.axe.run_agent_exec_plan_accept"


@dataclass(frozen=True)
class FollowupModel:
    """The follow-up agent's model directive prefix and metadata.

    ``model_prefix`` is prepended to the generated follow-up prompt (for
    example, ``"%model:codex/gpt-5.6-sol\\n"``). ``meta`` is the
    ``(provider_or_none, model)`` written to the follow-up's
    ``agent_meta.json``. It is ``None`` when the inherited planner metadata is
    already correct and does not need to be rewritten.
    """

    model_prefix: str
    meta: tuple[str | None, str] | None = None
    model_alias: str | None = None
    model_alias_trail: tuple[str, ...] = ()
    model_alias_origin: str | None = None


@dataclass(frozen=True)
class SuccessorRequest:
    """Inputs for :func:`continue_as_successor`.

    Exactly one of ``suffix`` or ``suffix_template`` must be set. An
    ``@``-bearing template is allocated when the agent is named and rendered
    with ``fallback_token`` when it is not.
    """

    base_meta: dict[str, Any]
    prompt: str
    suffix: str | None = None
    suffix_template: str | None = None
    extra_reserved_suffixes: tuple[str, ...] = ()
    agent_family_role: str | None = None
    relationships: dict[str, Any] = field(default_factory=dict)
    prompt_artifact_label: str = "Full follow-up prompt"
    model: FollowupModel | None = None
    promote_role_suffix: str | None = None
    fallback_token: str = "0"
    before_create: Callable[[str, str], None] | None = None

    def __post_init__(self) -> None:
        if (self.suffix is None) == (self.suffix_template is None):
            raise ValueError("exactly one of suffix or suffix_template must be set")


def _accept_binding[T](name: str, default: T) -> T:
    """Prefer a plan-accept module binding so its test doubles still apply."""
    module = sys.modules.get(_PLAN_ACCEPT_MODULE)
    if module is None:
        return default
    return getattr(module, name, default)


def _write_followup_model_alias_meta(
    artifacts_dir: str,
    model_alias: str | None,
    model_alias_trail: tuple[str, ...],
    model_alias_origin: str | None,
) -> None:
    """Set or clear the follow-up agent's launch-time alias provenance."""
    write_atomic = _accept_binding("write_agent_meta_atomic", write_agent_meta_atomic)
    index_updater = _accept_binding(
        "update_agent_artifact_index_for_marker_mutation",
        update_agent_artifact_index_for_marker_mutation,
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as handle:
            meta = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(meta, dict):
        return
    if model_alias:
        meta["model_alias"] = model_alias
    else:
        meta.pop("model_alias", None)
    if model_alias_trail:
        meta["model_alias_trail"] = list(model_alias_trail)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    elif model_alias:
        meta.pop("model_alias_trail", None)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    else:
        meta.pop("model_alias_trail", None)
        meta.pop("model_alias_origin", None)
    write_atomic(
        artifacts_dir,
        meta,
        index_updater=index_updater,
    )


def write_followup_model_meta(state: LoopState, followup: FollowupModel) -> None:
    """Record the follow-up agent's resolved model in its ``agent_meta.json``."""
    if followup.meta is None:
        return
    update = _accept_binding("update_meta_field", update_meta_field)
    resolved_provider, resolved_model = followup.meta
    update(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update(state.current_artifacts_dir, "llm_provider", resolved_provider)
    _write_followup_model_alias_meta(
        state.current_artifacts_dir,
        followup.model_alias,
        followup.model_alias_trail,
        followup.model_alias_origin,
    )


def _fallback_successor_suffix(template: str, *, token: str) -> str:
    from sase.agent.names import render_agent_name_template

    return render_agent_name_template(template, token)


def _resolved_suffix(
    ctx: AgentExecContext,
    request: SuccessorRequest,
) -> str:
    if request.suffix is not None:
        return request.suffix
    assert request.suffix_template is not None
    if ctx.agent_name:
        return allocate_agent_family_child_suffix(
            ctx.agent_name,
            request.suffix_template,
            extra_reserved_suffixes=request.extra_reserved_suffixes,
        )
    return _fallback_successor_suffix(
        request.suffix_template,
        token=request.fallback_token,
    )


def continue_as_successor(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    create_artifacts: Callable[..., str] | None = None,
    promote: Callable[..., None] | None = None,
    store_prompt: Callable[..., None] | None = None,
    write_model_meta: Callable[..., None] | None = None,
) -> str:
    """Become the next in-process family member and return its agent name."""
    create = create_followup_artifacts if create_artifacts is None else create_artifacts
    promote_fn = promote_to_workflow if promote is None else promote
    store = store_followup_prompt_artifact if store_prompt is None else store_prompt
    write_model = (
        write_followup_model_meta if write_model_meta is None else write_model_meta
    )

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

    suffix = _resolved_suffix(ctx, request)
    state.current_role_suffix = suffix
    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )
    if request.before_create is not None:
        request.before_create(suffix, successor_name)
    create_kwargs: dict[str, Any] = {
        "workspace_num": ctx.workspace_num,
        "agent_name_override": successor_name if ctx.agent_name else None,
        "workflow_name": ctx.agent_name,
        "relationships": request.relationships,
    }
    if request.agent_family_role is not None:
        create_kwargs["agent_family_role"] = request.agent_family_role
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


__all__ = [
    "FollowupModel",
    "SuccessorRequest",
    "continue_as_successor",
    "write_followup_model_meta",
]
