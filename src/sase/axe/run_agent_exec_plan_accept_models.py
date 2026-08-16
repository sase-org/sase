"""Model and effort helpers for accepted-plan coder follow-ups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.llm_provider.config import (
    format_model_directive_value,
    normalize_model_alias_reference,
)
from sase.tale_followup_routing import validated_tale_followup_model_directive

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext


@dataclass(frozen=True)
class FollowupModel:
    """The follow-up agent's model directive prefix and metadata.

    ``model_prefix`` is prepended to the generated follow-up prompt (for
    example, ``"%model:codex/gpt-5.6-sol\n"``). ``meta`` is the
    ``(provider_or_none, model)`` written to the follow-up's
    ``agent_meta.json``. It is ``None`` when the inherited planner metadata is
    already correct and does not need to be rewritten.
    """

    model_prefix: str
    meta: tuple[str | None, str] | None = None
    model_alias: str | None = None
    model_alias_trail: tuple[str, ...] = ()
    model_alias_origin: str | None = None


def resolve_model_meta(model_directive: str) -> tuple[str | None, str]:
    """Resolve a ``%model`` directive value to ``(provider_or_none, model)``."""
    from sase.llm_provider.registry import resolve_model_provider
    from sase.xprompt.effort import split_model_effort

    clean_model, _ = split_model_effort(model_directive)
    return resolve_model_provider(clean_model)


def resolve_model_alias_provenance(model_directive: str) -> tuple[tuple[str, ...], str]:
    """Resolve a follow-up ``%model`` directive value to alias trail/origin."""
    from sase.llm_provider.launch_selection import (
        ALIAS_ORIGIN_DIRECTIVE,
        ALIAS_ORIGIN_NONE,
    )
    from sase.llm_provider.model_alias_resolution import resolve_model_alias_with_effort
    from sase.xprompt.effort import split_model_effort

    clean_model, _ = split_model_effort(model_directive)
    resolved = resolve_model_alias_with_effort(clean_model)
    trail = resolved.alias_trail if resolved.valid else ()
    return trail, ALIAS_ORIGIN_DIRECTIVE if trail else ALIAS_ORIGIN_NONE


def _resolve_tale_size_followup(plan_file: str | Path) -> FollowupModel:
    """Route a coder follow-up through the tale's size-specific worker alias."""
    directive = validated_tale_followup_model_directive(plan_file)
    model_alias, _ = normalize_model_alias_reference(directive)
    model_alias_trail, model_alias_origin = resolve_model_alias_provenance(directive)
    return FollowupModel(
        model_prefix=f"%model:{directive}\n",
        meta=resolve_model_meta(directive),
        model_alias=model_alias,
        model_alias_trail=model_alias_trail,
        model_alias_origin=model_alias_origin,
    )


def resolve_followup_model(
    plan_result: Any,
    ctx: AgentExecContext,
    *,
    followup_plan_file: str | Path,
) -> FollowupModel:
    """Decide the follow-up agent's ``%model`` prefix and recorded metadata.

    An explicit approval-picker model wins. Otherwise, coder follow-ups route
    through the handoff tale's size-specific phase-worker alias. A model
    directive embedded in a custom coder prompt is handled by the caller and
    supersedes this result.
    """
    coder_model = plan_result.coder_model
    if coder_model and coder_model.strip() != "worker":
        directive_value = format_model_directive_value(coder_model)
        prefix = f"%model:{directive_value}\n"
        model_alias, _ = normalize_model_alias_reference(directive_value)
        model_alias_trail, model_alias_origin = resolve_model_alias_provenance(
            directive_value
        )
        if coder_model == ctx.agent_model:
            return FollowupModel(
                model_prefix=prefix,
                model_alias=model_alias,
                model_alias_trail=model_alias_trail,
                model_alias_origin=model_alias_origin,
            )
        return FollowupModel(
            model_prefix=prefix,
            meta=resolve_model_meta(coder_model),
            model_alias=model_alias,
            model_alias_trail=model_alias_trail,
            model_alias_origin=model_alias_origin,
        )

    return _resolve_tale_size_followup(followup_plan_file)


def custom_coder_prompt_model(
    coder_prompt: str | None,
) -> tuple[str, str | None] | None:
    """Return an explicit custom-prompt model directive, if one is present."""
    if not coder_prompt:
        return None
    from sase.xprompt._exceptions import DirectiveError
    from sase.xprompt.directives import extract_prompt_directives, has_model_directive

    if not has_model_directive(coder_prompt):
        return None
    directives = extract_prompt_directives(coder_prompt)[1]
    if not directives.model:
        raise DirectiveError("Custom coder prompt model directive requires a model")
    return directives.model, directives.model_alias


def plan_followup_base_meta(base_meta: dict[str, Any]) -> dict[str, Any]:
    """Return parent metadata minus effort for accepted plan-chain handoffs.

    Accepted coder follow-ups resolve effort from their own final prompt.
    Dropping the inherited value lets an unset follow-up omit
    ``reasoning_effort`` instead of displaying the planner's explicit effort.
    """
    if "reasoning_effort" not in base_meta:
        return base_meta
    return {key: value for key, value in base_meta.items() if key != "reasoning_effort"}
