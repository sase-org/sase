"""In-memory commit aggregation for synthetic agent-clan detail panels."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    ClanContextEntry,
    ClanContextLane,
)
from ...models.agent import Agent
from ._agent_commits import agent_commit_view_specs
from ._agent_display_state import CommitViewSpec


@dataclass(slots=True)
class _CommitAccumulator:
    key: str
    label: str
    member_labels: list[str] = field(default_factory=list)
    values: list[CommitViewSpec] = field(default_factory=list)
    count: int = 0

    def add(self, member_label: str, spec: CommitViewSpec) -> None:
        if member_label not in self.member_labels:
            self.member_labels.append(member_label)
        if spec not in self.values:
            self.values.append(spec)
        self.count += 1

    def freeze(self) -> ClanContextEntry:
        return ClanContextEntry(
            key=self.key,
            label=self.label,
            member_labels=tuple(self.member_labels),
            count=self.count,
            values=tuple(self.values),
        )


def aggregate_clan_commit_lane(
    rows: Collection[Agent],
    *,
    labels: Mapping[ClanAgentIdentity, str],
) -> ClanContextLane | None:
    """Aggregate ordered member commits, de-duplicating shared commit SHAs."""
    entries: OrderedDict[str, _CommitAccumulator] = OrderedDict()
    for row in rows:
        member_label = labels.get(row.identity, row.display_name)
        for spec, repo_name, repo_kind in agent_commit_view_specs(row):
            sha = spec.sha.strip()
            key = (
                sha.casefold()
                if sha
                else (f"{repo_kind}:{repo_name}:{spec.short_sha}:{spec.subject}")
            )
            label = f"{spec.short_sha} {spec.subject}".strip()
            entry = entries.get(key)
            if entry is None:
                entry = _CommitAccumulator(key=key, label=label)
                entries[key] = entry
            entry.add(member_label, spec)
    if not entries:
        return None
    return ClanContextLane(
        label="COMMITS",
        entries=tuple(entry.freeze() for entry in entries.values()),
    )
