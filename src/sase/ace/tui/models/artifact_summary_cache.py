"""In-memory artifact summary cache for CL/Agent row indicators."""

from __future__ import annotations

from collections.abc import Iterable

from sase.core.artifact_wire import ArtifactSummaryWire


class ArtifactSummaryCache:
    """Tiny mutable cache invalidated by unified artifact refresh events."""

    def __init__(self) -> None:
        self._summaries: dict[str, ArtifactSummaryWire] = {}
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    def get(self, artifact_id: str) -> ArtifactSummaryWire | None:
        return self._summaries.get(artifact_id)

    def update(self, summaries: Iterable[ArtifactSummaryWire]) -> None:
        for summary in summaries:
            self._summaries[summary.artifact_id] = summary

    def invalidate(self, artifact_ids: Iterable[str] | None = None) -> None:
        if artifact_ids is None:
            self._summaries.clear()
            self._version += 1
            return

        removed = False
        for artifact_id in artifact_ids:
            removed = self._summaries.pop(artifact_id, None) is not None or removed
        if removed:
            self._version += 1


__all__ = ["ArtifactSummaryCache"]
