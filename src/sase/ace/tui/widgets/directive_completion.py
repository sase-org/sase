"""Pure-logic directive completion engine for the prompt input bar."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    filter_agent_completion_candidates,
)
from sase.ace.tui.widgets._directive_completion_tokens import (
    canonical_directive_name as _canonical_directive_name,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
    selected_wait_values_around_cursor,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables
from sase.llm_provider.temporary_override import peek_active_alias_overrides
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


@dataclass(frozen=True, slots=True)
class ModelCompletionMetadata:
    """Display metadata for an enriched ``%model`` completion row."""

    value: str
    kind: str
    alias_kind: str = ""
    provider: str = ""
    provider_display: str = ""
    short_alias: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    provenance: str = ""
    reference: str = ""
    reference_effort: str = ""
    pool_available: int = 0
    pool_total: int = 0
    description: str = ""
    config_source: str = ""
    provider_model_count: int = 0


class _ModelEntryDisplay(Protocol):
    """Catalog scalars used to recover the provider's display label."""

    @property
    def kind(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def aliases(self) -> tuple[str, ...]: ...


_DIRECTIVE_ARGUMENT_HINTS: dict[str, str] = {
    "alt": "(variants)",
    "auto": ":argument (e.g. plan|tale|epic)",
    "clan": (
        ":name or :name.{@key}, "
        "(name, tribe=/summary=/summary_script=), or :name:: summary"
    ),
    "effort": ":level",
    "hide": "flag",
    "model": ":model or (model, alias=model)",
    "id": (":agent-id or :name.{@key}; ([id], bead=bead, clan=/family=/tribe=)"),
    "repeat": ":count",
    "wait": ":agent or (agent, time=5m, runners=1, priority=10)",
}


_DIRECTIVE_DESCRIPTIONS: dict[str, str] = {
    "alt": "split a prompt into variants; shorthand %{A | B}",
    "auto": "request automatic gate resolution; arguments are gate-specific",
    "clan": "declare a parallel agent clan; use {@key} for swarm-safe templates",
    "effort": "set the reasoning-effort level for this prompt",
    "hide": "hide the agent from the default Agents tab",
    "model": "choose a model and optional launch-family alias overrides",
    "id": "assign an agent id/template with optional bead, clan, family, or tribe",
    "repeat": "run the prompt multiple serial iterations",
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
    ("priority=", "lower values start first; the default is 10"),
    ("runners=", "start when at most this many agents are already running"),
    ("time=", "start after a duration or absolute wall-clock time"),
)

_CLAN_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("summary=", "attach a literal Rich-markup clan summary"),
    ("summary_script=", "run an executable to produce the clan summary"),
    ("tribe=", "assign one tribe to the entire clan"),
)

_ID_KEYWORD_ARGUMENTS: tuple[tuple[str, str], ...] = (
    ("bead=", "associate this launch with a bead"),
    ("clan=", "derive the full name and join this agent clan"),
    ("family=", "attach this suffix to an existing agent family"),
    ("tribe=", "assign this agent to a user-managed tribe"),
)

_TARGET_KIND_ORDER = ("tribe", "clan", "family", "agent")


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
    selected_values: frozenset[str] = frozenset(),
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
    if directive_name == "id_keyword":
        return _build_keyword_completion_candidates(
            partial,
            directive_name="id",
            keywords=_ID_KEYWORD_ARGUMENTS,
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
        return _build_wait_arg_completion_candidates(
            partial,
            agent_candidates,
            selected_values=selected_values,
        )

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
    """Build kind-aware target candidates for a wait/fork argument."""
    if "=" in partial:
        return [], ""

    partial_lower = partial.lower()
    source_entries = list(agent_candidates or ())
    source_entries = [*_derived_tribe_entries(source_entries), *source_entries]
    excluded = {name.casefold() for name in excluded_names}
    matching = [
        entry
        for entry in filter_agent_completion_candidates(source_entries, partial)
        if not _target_is_excluded(entry, excluded)
    ]
    ordered = [
        entry for kind in _TARGET_KIND_ORDER for entry in matching if entry.kind == kind
    ]
    candidates: list[CompletionCandidate] = []
    seen_insertions: set[str] = set()
    for entry in ordered:
        if entry.name in seen_insertions:
            continue
        seen_insertions.add(entry.name)
        candidates.append(
            CompletionCandidate(
                display=entry.name,
                insertion=entry.name,
                is_dir=False,
                name=entry.name,
                metadata=entry,
            )
        )

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


def _derived_tribe_entries(
    entries: Sequence[AgentCompletionCandidate],
) -> list[AgentCompletionCandidate]:
    """Derive aggregate tribe rows from flat agent completion candidates."""
    explicit = {entry.name for entry in entries if entry.kind == "tribe"}
    members_by_tribe: dict[str, list[AgentCompletionCandidate]] = {}
    for entry in entries:
        if entry.kind != "agent" or not entry.tribe:
            continue
        tribe = entry.tribe if entry.tribe.startswith("@") else f"@{entry.tribe}"
        if tribe in explicit:
            continue
        members_by_tribe.setdefault(tribe, []).append(entry)

    legacy: list[AgentCompletionCandidate] = []
    for tribe, members in members_by_tribe.items():
        statuses = [member.status for member in members]
        from sase.ace.tui.models._agent_clan import aggregate_clan_status

        status = aggregate_clan_status(statuses) or "RUNNING"
        legacy.append(
            AgentCompletionCandidate(
                name=tribe,
                label=tribe.removeprefix("@"),
                status=status,
                kind="tribe",
                member_count=len(members),
                aggregate_status=status,
                member_names=tuple(member.name for member in members),
                agent_count=len(members),
                clan_count=0,
                search_aliases=(tribe.removeprefix("@"),),
            )
        )
    return legacy


def _target_is_excluded(
    entry: AgentCompletionCandidate,
    excluded: set[str],
) -> bool:
    canonical = entry.name.casefold()
    if canonical in excluded:
        return True
    return entry.kind == "tribe" and canonical.removeprefix("@") in excluded


def _build_wait_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    selected_values: frozenset[str] = frozenset(),
) -> tuple[list[CompletionCandidate], str]:
    """Build agent-name and keyword candidates for ``%wait`` arguments."""
    agents, _ = build_agent_arg_completion_candidates(
        partial,
        agent_candidates,
        excluded_names=selected_values,
    )
    partial_lower = partial.lower()
    selected = {value.casefold() for value in selected_values}
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
        and not any(
            selected_value.startswith(value.casefold()) for selected_value in selected
        )
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
        build_model_completion_catalog(
            overrides=peek_active_alias_overrides(),
            provider_disables=peek_active_provider_disables(),
        ),
        partial,
    )
    candidates = [
        CompletionCandidate(
            display=entry.display,
            insertion=entry.value,
            is_dir=entry.kind == "provider",
            name=entry.value,
            metadata=ModelCompletionMetadata(
                value=entry.value,
                kind=entry.kind,
                alias_kind=entry.alias_kind,
                provider=entry.provider,
                provider_display=_model_provider_display(entry),
                short_alias=(
                    entry.aliases[0] if entry.kind == "model" and entry.aliases else ""
                ),
                target_provider=entry.target_provider,
                target_model=entry.target_model,
                target_effort=entry.target_effort,
                provenance=entry.provenance,
                reference=entry.reference,
                reference_effort=entry.reference_effort,
                pool_available=entry.pool_available,
                pool_total=entry.pool_total,
                description=entry.description,
                config_source=entry.config_source,
                provider_model_count=entry.provider_model_count,
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


def _model_provider_display(entry: _ModelEntryDisplay) -> str:
    """Extract the provider display label retained in a model entry."""
    if entry.kind == "provider":
        return entry.description
    if entry.kind != "model":
        return ""
    if not entry.aliases:
        return entry.description
    suffix = f" ({entry.aliases[0]})"
    return entry.description.removesuffix(suffix)


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
