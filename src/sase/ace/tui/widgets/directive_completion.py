"""Pure-logic directive completion engine for the prompt input bar."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    filter_agent_completion_candidates,
)
from sase.ace.tui.widgets._directive_completion_tokens import (
    canonical_directive_name as _canonical_directive_name,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt._directive_types import (
    AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
    _DIRECTIVE_ALIASES,
    _KNOWN_DIRECTIVES,
)
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import (
    build_model_completion_catalog,
    filter_model_completion_entries,
)

_USER_FACING_DIRECTIVES = frozenset((*_KNOWN_DIRECTIVES, "alt"))


@dataclass(frozen=True, slots=True)
class DirectiveCompletionMetadata:
    """Display metadata for a prompt directive completion candidate."""

    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DirectiveArgCompletionMetadata:
    """Display metadata for a prompt directive argument completion candidate."""

    directive_name: str = ""
    description: str = ""


_DIRECTIVE_ARGUMENT_HINTS: dict[str, str] = {
    "alt": "(variants)",
    "auto": ":argument (e.g. plan|tale|epic)",
    "clan": ":name or (name, tribe=tribe)",
    "effort": ":level",
    "hide": "flag",
    "model": ":model or (model, alias=model)",
    "name": ":agent or (parent, suffix)",
    "repeat": ":count",
    "tribe": ":name",
    "wait": ":agent or (agent, time=5m, runners=1)",
}


_DIRECTIVE_DESCRIPTIONS: dict[str, str] = {
    "alt": "split a prompt into variants; shorthand %{A | B}",
    "auto": "request automatic gate resolution; arguments are gate-specific",
    "clan": "join a named parallel agent clan",
    "effort": "set the reasoning-effort level for this prompt",
    "hide": "hide the agent from the default Agents tab",
    "model": "choose a model and optional launch-family alias overrides",
    "name": "assign an agent name or attach a member to an existing family",
    "repeat": "run the prompt multiple serial iterations",
    "tribe": "assign a user-managed agent tribe",
    "wait": "defer launch for agents, a time floor, or a runner threshold",
}

_EFFORT_ARGUMENT_DESCRIPTIONS: dict[str, str] = {
    "none": "no reasoning-effort override",
    "minimal": "minimal reasoning effort",
    "low": "low reasoning effort",
    "medium": "medium reasoning effort",
    "high": "high reasoning effort",
    "xhigh": "extra-high reasoning effort",
    "max": "maximum reasoning effort",
}

_AUTO_ARGUMENT_DESCRIPTIONS: dict[str, str] = {
    "plan": "plan-gate compatibility alias for normal approval",
    "tale": "plan-gate compatibility alias for SDD tale approval",
    "epic": "plan-gate compatibility alias for SDD epic approval",
}

_DIRECTIVE_ARGUMENT_VALUES: dict[str, tuple[str, ...]] = {
    "effort": EFFORT_LEVELS_ORDERED,
    "auto": AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS,
}

_DIRECTIVE_ARGUMENT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "effort": _EFFORT_ARGUMENT_DESCRIPTIONS,
    "auto": _AUTO_ARGUMENT_DESCRIPTIONS,
}

_WAIT_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("runners=", "start when at most this many agents are already running"),
    ("time=", "start after a duration or absolute wall-clock time"),
)

_CLAN_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("tribe=", "assign one tribe to the entire clan"),
)


def build_directive_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a directive token."""
    if not is_directive_like_token(token):
        return [], ""

    partial = token[1:]
    partial_lower = partial.lower()
    aliases_by_directive = _aliases_by_directive()
    candidates = [
        CompletionCandidate(
            display=f"%{directive}",
            insertion=f"%{directive}",
            is_dir=False,
            name=directive,
            metadata=DirectiveCompletionMetadata(
                aliases=aliases_by_directive.get(directive, ()),
                argument_hint=_DIRECTIVE_ARGUMENT_HINTS.get(directive, ""),
                description=_DIRECTIVE_DESCRIPTIONS.get(directive, ""),
            ),
        )
        for directive in sorted(_USER_FACING_DIRECTIVES)
        if _matches_directive(directive, aliases_by_directive, partial_lower)
    ]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion[1:] for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def build_directive_arg_completion_candidates(
    directive_name: str,
    partial: str,
    *,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build fixed-value candidates for a directive argument token."""
    if directive_name == "model_alias_key":
        return _build_model_alias_key_completion_candidates(partial)
    if directive_name == "clan_keyword":
        return _build_keyword_completion_candidates(
            partial,
            directive_name="clan",
            keywords=_CLAN_KEYWORD_ARGUMENTS,
        )
    if directive_name == "model_or_alias_key":
        models, _ = _build_model_arg_completion_candidates(partial)
        aliases, _ = _build_model_alias_key_completion_candidates(partial)
        return [*models, *aliases], ""
    canonical = _canonical_directive_name(directive_name)
    if canonical is None:
        return [], ""

    if canonical == "model":
        return _build_model_arg_completion_candidates(partial)
    if canonical == "wait":
        return _build_wait_arg_completion_candidates(partial, agent_candidates)

    values = _DIRECTIVE_ARGUMENT_VALUES.get(canonical)
    if values is None:
        return [], ""

    partial_lower = partial.lower()
    descriptions = _DIRECTIVE_ARGUMENT_DESCRIPTIONS.get(canonical, {})
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value,
            metadata=DirectiveArgCompletionMetadata(
                directive_name=canonical,
                description=descriptions.get(value, ""),
            ),
        )
        for value in values
        if value.lower().startswith(partial_lower)
    ]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def build_agent_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    excluded_names: frozenset[str] = frozenset(),
) -> tuple[list[CompletionCandidate], str]:
    """Build visible-agent and tribe candidates for a wait/fork argument."""
    if "=" in partial:
        return [], ""

    partial_lower = partial.lower()
    tribe_names = sorted(
        {
            entry.tag
            for entry in agent_candidates or ()
            if entry.tag
            and entry.tag not in excluded_names
            and entry.tag.lower().startswith(partial_lower)
        },
        key=str.lower,
    )
    tribe_candidates = [
        CompletionCandidate(
            display=tribe_name,
            insertion=tribe_name,
            is_dir=False,
            name=tribe_name,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="tribe",
                description="target the next agent or clan joining this tribe",
            ),
        )
        for tribe_name in tribe_names
    ]
    entries = [
        entry
        for entry in filter_agent_completion_candidates(agent_candidates, partial)
        if entry.name not in excluded_names
    ]
    candidates = [
        CompletionCandidate(
            display=entry.name,
            insertion=entry.name,
            is_dir=False,
            name=entry.name,
            metadata=entry,
        )
        for entry in entries
    ]
    candidates = [*tribe_candidates, *candidates]

    shared_extension = ""
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def _build_wait_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
) -> tuple[list[CompletionCandidate], str]:
    """Build agent-name and keyword candidates for ``%wait`` arguments."""
    agents, _ = build_agent_arg_completion_candidates(partial, agent_candidates)
    partial_lower = partial.lower()
    keywords = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value[:-1],
            metadata=DirectiveArgCompletionMetadata(
                directive_name="wait",
                description=description,
            ),
        )
        for value, description in _WAIT_KEYWORD_ARGUMENTS
        if value.lower().startswith(partial_lower)
    ]
    candidates = [*keywords, *agents]

    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]
    return candidates, shared_extension


def _build_keyword_completion_candidates(
    partial: str,
    *,
    directive_name: str,
    keywords: tuple[tuple[str, str], ...],
) -> tuple[list[CompletionCandidate], str]:
    partial_lower = partial.lower()
    candidates = [
        CompletionCandidate(
            display=value,
            insertion=value,
            is_dir=False,
            name=value[:-1],
            metadata=DirectiveArgCompletionMetadata(
                directive_name=directive_name,
                description=description,
            ),
        )
        for value, description in keywords
        if value.lower().startswith(partial_lower)
    ]
    return candidates, ""


def _build_model_arg_completion_candidates(
    partial: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build dynamic candidates for a ``%model`` directive argument token."""
    entries = filter_model_completion_entries(
        build_model_completion_catalog(),
        partial,
    )
    candidates = [
        CompletionCandidate(
            display=entry.display,
            insertion=entry.value,
            is_dir=False,
            name=entry.value,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="model",
                description=entry.description,
            ),
        )
        for entry in entries
    ]

    shared_extension = ""
    partial_lower = partial.lower()
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]

    return candidates, shared_extension


def _build_model_alias_key_completion_candidates(
    partial: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build ``alias=`` candidates for parenthesized ``%model`` kwargs."""
    from sase.llm_provider.config import model_alias_description, model_alias_names

    partial_lower = partial.lower()
    candidates = [
        CompletionCandidate(
            display=f"{alias}=",
            insertion=f"{alias}=",
            is_dir=False,
            name=alias,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="model",
                description=model_alias_description(alias) or "model alias override",
            ),
        )
        for alias in sorted(model_alias_names())
        if alias.lower().startswith(partial_lower)
    ]
    shared_extension = ""
    if len(candidates) > 1:
        shared_prefix = os.path.commonprefix(
            [candidate.insertion for candidate in candidates]
        )
        if len(shared_prefix) > len(partial):
            shared_extension = shared_prefix[len(partial) :]
    return candidates, shared_extension


def _matches_directive(
    directive: str,
    aliases_by_directive: dict[str, tuple[str, ...]],
    partial_lower: str,
) -> bool:
    if directive.lower().startswith(partial_lower):
        return True
    return any(
        alias.startswith(partial_lower) for alias in aliases_by_directive[directive]
    )


def _aliases_by_directive() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {
        directive: [] for directive in _USER_FACING_DIRECTIVES
    }
    for alias, canonical in _DIRECTIVE_ALIASES.items():
        if canonical in grouped:
            grouped[canonical].append(alias)
    return {directive: tuple(sorted(aliases)) for directive, aliases in grouped.items()}
