"""Xprompt argument completion helpers for prompt file completion."""

from __future__ import annotations

import os
from collections.abc import Sequence

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.file_completion import (
    CompletionCandidate,
    build_completion_candidates,
    is_path_like_token,
)
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptArgCompletionContext


def effective_xprompt_arg_token(ctx: XPromptArgCompletionContext) -> str:
    """Return the token passed to an underlying completion engine."""
    if ctx.completion_kind != "xprompt_arg_path":
        return ctx.token
    if not ctx.token:
        return "./"
    if is_path_like_token(ctx.token):
        return ctx.token
    return f"./{ctx.token}"


def build_xprompt_arg_completion_candidates(
    ctx: XPromptArgCompletionContext,
    *,
    base_dir: str | os.PathLike[str] | None = None,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for an xprompt argument completion context."""
    if ctx.completion_kind == "xprompt_arg_path":
        return build_completion_candidates(
            effective_xprompt_arg_token(ctx),
            base_dir=base_dir,
        )
    if ctx.completion_kind == "xprompt_arg_value":
        return _build_bool_completion_candidates(ctx.token)
    if ctx.completion_kind == "xprompt_arg_agent":
        from sase.ace.tui.widgets.directive_completion import (
            build_agent_arg_completion_candidates,
        )

        return build_agent_arg_completion_candidates(
            ctx.token,
            agent_candidates,
            excluded_names=ctx.selected_values,
        )
    if ctx.completion_kind == "xprompt_arg_name":
        return _build_named_arg_completion_candidates(ctx)
    return [], ""


def _build_bool_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    partial = token.lower()
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value,
        )
        for value in ("true", "false")
        if value.startswith(partial)
    ]
    return candidates, ""


def cursor_prefix_may_contain_xprompt_args(text: str, cursor_offset: int) -> bool:
    """Return True when the cursor prefix has possible xprompt arg syntax."""
    prefix = text[:cursor_offset]
    marker = prefix.rfind("#")
    if marker == -1:
        return False
    suffix = prefix[marker:]
    return ":" in suffix or "(" in suffix


def _build_named_arg_completion_candidates(
    ctx: XPromptArgCompletionContext,
) -> tuple[list[CompletionCandidate], str]:
    partial = ctx.token.lower()
    candidates = [
        CompletionCandidate(
            display=f"{inp.name}=",
            insertion=f"{inp.name}=",
            is_dir=False,
            name=inp.name,
            metadata=inp,
        )
        for inp in ctx.entry.inputs
        if inp.name not in ctx.used_arg_names and inp.name.lower().startswith(partial)
    ]
    candidates.sort(key=lambda c: c.name.lower())
    return candidates, ""
