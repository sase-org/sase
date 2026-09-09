"""Small statistics helpers for the artifact-link outbox."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil
import time


@dataclass(frozen=True, slots=True)
class _ArtifactLinkOutboxAgeStats:
    oldest_age_seconds: float = 0.0
    newest_age_seconds: float = 0.0
    p95_age_seconds: float = 0.0


def artifact_link_outbox_age_stats(
    created_at_values: Iterable[float],
    *,
    now: float | None,
) -> _ArtifactLinkOutboxAgeStats:
    observed_at = float(time.time() if now is None else now)
    ages = sorted(
        max(0.0, observed_at - float(created_at)) for created_at in created_at_values
    )
    if not ages:
        return _ArtifactLinkOutboxAgeStats()
    p95_index = min(len(ages) - 1, max(0, ceil(len(ages) * 0.95) - 1))
    return _ArtifactLinkOutboxAgeStats(
        oldest_age_seconds=ages[-1],
        newest_age_seconds=ages[0],
        p95_age_seconds=ages[p95_index],
    )
