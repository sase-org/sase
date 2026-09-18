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
_TARGET_KIND_ORDER = ("hood", "tribe", "clan", "family", "agent", "proc")
_PRE_RUN_STATUS_RANK = {"WAITING": 0, "QUEUED": 1}


def build_agent_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    excluded_names: frozenset[str] = frozenset(),
    required_kind: str | None = None,
    excluded_kinds: frozenset[str] = frozenset(),
    prioritize_pre_run: bool = False,
    proc_insertion: str = "name",
) -> tuple[list[CompletionCandidate], str]:
    """Build kind-aware target candidates for a wait/fork/identity argument."""
    if "=" in partial:
        return [], ""

    partial_lower = partial.lower()
    base_entries = list(agent_candidates or ())
    if required_kind == "hood":
        source_entries = _derived_hood_entries(base_entries)
    else:
        source_entries = [*_derived_tribe_entries(base_entries), *base_entries]
    if required_kind is not None:
        source_entries = [
            entry for entry in source_entries if entry.kind == required_kind
        ]
    if excluded_kinds:
        source_entries = [
            entry for entry in source_entries if entry.kind not in excluded_kinds
        ]
    excluded = {name.casefold() for name in excluded_names}
    matching = [
        entry
        for entry in filter_agent_completion_candidates(source_entries, partial)
        if not _target_is_excluded(
            entry,
            excluded,
            proc_insertion=proc_insertion,
        )
    ]
    ordered = _ordered_targets(matching, prioritize_pre_run=prioritize_pre_run)
    candidates: list[CompletionCandidate] = []
    seen_insertions: set[str] = set()
    for entry in ordered:
        insertion = _target_insertion(entry, proc_insertion=proc_insertion)
        if not insertion or insertion in seen_insertions:
            continue
        seen_insertions.add(insertion)
        candidates.append(
            CompletionCandidate(
                display=insertion,
                insertion=insertion,
                is_dir=False,
                name=insertion,
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


def _ordered_targets(
    entries: Sequence[AgentCompletionCandidate],
    *,
    prioritize_pre_run: bool,
) -> list[AgentCompletionCandidate]:
    if not prioritize_pre_run:
        return [
            entry
            for kind in _TARGET_KIND_ORDER
            for entry in entries
            if entry.kind == kind
        ]
    kind_index = {kind: index for index, kind in enumerate(_TARGET_KIND_ORDER)}
    return [
        entry
        for _index, entry in sorted(
            enumerate(entries),
            key=lambda item: (
                _PRE_RUN_STATUS_RANK.get(item[1].status.upper(), 2),
                kind_index.get(item[1].kind, len(kind_index)),
                item[0],
            ),
        )
    ]


def _target_insertion(
    entry: AgentCompletionCandidate,
    *,
    proc_insertion: str,
) -> str:
    if entry.kind == "proc" and proc_insertion == "label":
        return entry.label or entry.name
    return entry.name


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


def _derived_hood_entries(
    entries: Sequence[AgentCompletionCandidate],
) -> list[AgentCompletionCandidate]:
    """Derive aggregate hood rows from visible agent and proc shell names."""
    explicit = {entry.name for entry in entries if entry.kind == "hood"}
    members_by_hood: dict[str, list[AgentCompletionCandidate]] = {}
    for entry in entries:
        if entry.kind == "tribe":
            continue
        source_name = (
            entry.label if entry.kind == "proc" and entry.label else entry.name
        )
        for hood in _agent_hoods(source_name):
            if hood in explicit:
                continue
            members_by_hood.setdefault(hood, []).append(entry)

    derived: list[AgentCompletionCandidate] = [
        entry for entry in entries if entry.kind == "hood"
    ]
    for hood, members in members_by_hood.items():
        statuses = [member.status for member in members]
        from sase.ace.tui.models._agent_clan import aggregate_clan_status

        status = aggregate_clan_status(statuses) or "RUNNING"
        derived.append(
            AgentCompletionCandidate(
                name=hood,
                label=hood,
                status=status,
                kind="hood",
                member_count=len(members),
                aggregate_status=status,
                member_names=tuple(member.name for member in members),
                agent_count=sum(member.kind != "proc" for member in members),
                clan_count=0,
            )
        )
    return derived


def _agent_hoods(name: str) -> tuple[str, ...]:
    try:
        from sase.core.agent_identity_facade import agent_name_ancestors

        return tuple(agent_name_ancestors(name))
    except Exception:
        return ()


def _target_is_excluded(
    entry: AgentCompletionCandidate,
    excluded: set[str],
    *,
    proc_insertion: str,
) -> bool:
    canonical = entry.name.casefold()
    insertion = _target_insertion(entry, proc_insertion=proc_insertion).casefold()
    if canonical in excluded or insertion in excluded:
        return True
    return entry.kind == "tribe" and canonical.removeprefix("@") in excluded
