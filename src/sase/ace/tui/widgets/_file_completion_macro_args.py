"""Macro argument completion helpers for prompt file completion."""

from __future__ import annotations

import os
from collections.abc import Sequence

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    build_completion_candidates,
    is_path_like_token,
)
from dataclasses import dataclass

from sase.ace.tui.widgets.macro_arg_assist import (
    MacroArgCompletionContext,
    MacroArgNameMetadata,
)
from sase.ace.tui.widgets._macro_arg_choice_adapter import (
    choice_candidates_for_hint,
)
from sase.macro.model_completion import ModelCompletionEntry


@dataclass(frozen=True, slots=True)
class MacroArgValueMetadata:
    """Typed metadata for one enum/bool choice row."""

    value: str
    label: str | None = None
    description: str | None = None
    is_default: bool = False
    choice_index: int = 0
    input_name: str = ""
    type_label: str = ""


def effective_macro_arg_token(ctx: MacroArgCompletionContext) -> str:
    """Return the token passed to an underlying completion engine."""
    if ctx.completion_kind != "macro_arg_path":
        return ctx.token
    if not ctx.token:
        return "./"
    if is_path_like_token(ctx.token):
        return ctx.token
    return f"./{ctx.token}"


def build_macro_arg_completion_candidates(
    ctx: MacroArgCompletionContext,
    *,
    base_dir: str | os.PathLike[str] | None = None,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for a macro argument completion context."""
    if ctx.completion_kind == "macro_arg_path":
        return build_completion_candidates(
            effective_macro_arg_token(ctx),
            base_dir=base_dir,
        )
    if ctx.completion_kind == "macro_arg_value":
        return _build_choice_completion_candidates(ctx)
    if ctx.completion_kind == "macro_arg_agent":
        from sase.ace.tui.widgets.directive_completion import (
            build_agent_arg_completion_candidates,
        )

        return build_agent_arg_completion_candidates(
            ctx.token,
            agent_candidates,
            excluded_names=ctx.selected_values,
        )
    if ctx.completion_kind == "macro_arg_name":
        return _build_named_arg_completion_candidates(ctx)
    return [], ""


def build_macro_arg_model_completion_candidates(
    ctx: MacroArgCompletionContext,
    entries: Sequence[ModelCompletionEntry] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build macro model candidates through the shared ``%model`` builder."""
    from sase.ace.tui.widgets._directive_completion_tokens import (
        synthetic_directive_clause,
    )
    from sase.ace.tui.widgets.directive_completion import (
        build_directive_clause_candidates,
    )

    is_effort = ctx.model_effort
    clause = synthetic_directive_clause(
        kind="directive_argument",
        token=ctx.token,
        directive_name="effort" if is_effort else "model",
        value_role="free_text" if is_effort else "model",
        selected_values=ctx.selected_values,
    )
    if is_effort:
        return build_directive_clause_candidates(clause)
    if entries is None:
        return [], ""
    return build_directive_clause_candidates(clause, model_entries=entries)


def _build_choice_completion_candidates(
    ctx: MacroArgCompletionContext,
) -> tuple[list[CompletionCandidate], str]:
    """Build enum/bool value candidates through the shared Rust builder."""
    active = ctx.active_input
    if active is None:
        return [], ""
    # Partial is text before the cursor without surrounding quote wrapper;
    # replacement is the whole current value/element for repeatable detection.
    raw_token = ctx.token
    partial = raw_token.lstrip("\"'")
    replacement = ctx.replacement or raw_token
    rows = choice_candidates_for_hint(
        active,
        partial=partial,
        replacement=replacement,
        selected=ctx.selected_values,
    )
    type_label = active.named_type or active.type
    candidates = [
        CompletionCandidate(
            display=row.value,
            insertion=row.insertion,
            is_dir=False,
            name=row.value,
            metadata=MacroArgValueMetadata(
                value=row.value,
                label=row.label,
                description=row.description,
                is_default=row.is_default,
                choice_index=row.index,
                input_name=active.name,
                type_label=type_label,
            ),
        )
        for row in rows
    ]
    return candidates, ""


def cursor_prefix_may_contain_macro_args(text: str, cursor_offset: int) -> bool:
    """Return True when the cursor prefix has possible macro arg syntax."""
    prefix = text[:cursor_offset]
    marker = prefix.rfind("#")
    if marker == -1:
        return False
    suffix = prefix[marker:]
    return ":" in suffix or "(" in suffix


def _build_named_arg_completion_candidates(
    ctx: MacroArgCompletionContext,
) -> tuple[list[CompletionCandidate], str]:
    partial = ctx.token.lower()
    candidates = [
        CompletionCandidate(
            display=f"{inp.name}=",
            insertion=f"{inp.name}=",
            is_dir=False,
            name=inp.name,
            metadata=MacroArgNameMetadata(
                reference_text=ctx.entry.insertion,
                input_hint=inp,
            ),
        )
        for inp in ctx.entry.inputs
        if inp.name not in ctx.used_arg_names and inp.name.lower().startswith(partial)
    ]
    return candidates, ""
