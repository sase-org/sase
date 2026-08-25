"""Agent target candidates for ACE prompt directive completion."""

from __future__ import annotations

from collections.abc import Sequence

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    filter_agent_completion_candidates,
)
from sase.ace.tui.widgets._directive_completion_candidates import shared_extension
from sase.ace.tui.widgets.file_completion import CompletionCandidate

IDENTITY_ROLES = frozenset({"clan", "family", "tribe"})
_TARGET_KIND_ORDER = ("tribe", "clan", "family", "agent", "proc")


def build_agent_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    excluded_names: frozenset[str] = frozenset(),
    required_kind: str | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build kind-aware target candidates for a wait/fork/identity argument."""
    if "=" in partial:
        return [], ""

    partial_lower = partial.lower()
    source_entries = list(agent_candidates or ())
    source_entries = [*_derived_tribe_entries(source_entries), *source_entries]
    if required_kind is not None:
        source_entries = [
            entry for entry in source_entries if entry.kind == required_kind
        ]
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

    shared = ""
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared = shared_extension(
            [candidate.insertion for candidate in candidates],
            partial,
        )
    return candidates, shared


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
