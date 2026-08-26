"""Rank audited reads into citation candidates -- not artifact-link rows.

Per PROV and OpenLineage, an activity *using* an entity is not the output
being a *derivation* of it, so a read never gets promoted to a row here.
This module only aggregates and ranks; the judgment layer that turns a
candidate into a persisted row -- `sase artifact link suggest` -- lands in
a later phase and stores nothing itself either.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.artifact_read_log import ArtifactReadEvent


@dataclass(frozen=True, slots=True)
class _ReadCitationCandidate:
    """One ``(agent, ref)`` pairing ranked by how often it recurred."""

    agent_name: str
    ref: str
    reason: str
    reads: int
    latest_timestamp: str


def rank_read_citation_candidates(
    events: Sequence[ArtifactReadEvent],
) -> tuple[_ReadCitationCandidate, ...]:
    """Aggregate every read event into one ranked candidate per (agent, ref).

    Scoped to every read, not a `plan:`/`research:` subset (owner decision
    4 in the derivation epic): filtering by ref kind is the candidate
    surface's job, not this function's. The candidate's reason is the most
    recent read's own stated reason, since a stale reason from an earlier
    read describes the citation worse than a fresher one. Ranked by read
    count, then deterministically by ref and agent name.
    """

    counts: dict[tuple[str, str], int] = {}
    latest: dict[tuple[str, str], ArtifactReadEvent] = {}
    for event in events:
        key = (event.agent_name, event.ref)
        counts[key] = counts.get(key, 0) + 1
        current = latest.get(key)
        if current is None or event.timestamp >= current.timestamp:
            latest[key] = event

    candidates = [
        _ReadCitationCandidate(
            agent_name=agent_name,
            ref=ref,
            reason=latest[(agent_name, ref)].reason,
            reads=count,
            latest_timestamp=latest[(agent_name, ref)].timestamp,
        )
        for (agent_name, ref), count in counts.items()
    ]
    candidates.sort(
        key=lambda candidate: (-candidate.reads, candidate.ref, candidate.agent_name)
    )
    return tuple(candidates)


__all__ = ["rank_read_citation_candidates"]
