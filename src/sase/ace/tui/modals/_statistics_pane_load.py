"""Worker payload type for Statistics pane loads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.stats.loader import StatisticsViewData
from sase.stats.project import ProjectStatsView


@dataclass(frozen=True, slots=True)
class StatisticsLoadResult:
    """Worker payload carrying the selection generation that produced it."""

    generation: int
    kind: Literal["primary", "code"]
    payload: StatisticsViewData | ProjectStatsView


__all__ = ["StatisticsLoadResult"]
