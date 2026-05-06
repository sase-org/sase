"""Shared artifact row indicator model and renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from sase.core.artifact_wire import ArtifactSummaryWire, ArtifactTypeCountWire
from sase.core.artifact_wire.constants import (
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_MISC,
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_DIRECTORY,
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_ROOT,
    ARTIFACT_KIND_THOUGHT,
    ARTIFACT_KIND_UNKNOWN,
)

ArtifactIndicatorState = Literal["ok", "missing", "loading", "stale", "error"]

FILE_TYPE_COUNT_ORDER = (
    ARTIFACT_FILE_TYPE_PLAN,
    ARTIFACT_FILE_TYPE_DIFF,
    ARTIFACT_FILE_TYPE_CHAT,
    ARTIFACT_FILE_TYPE_PROJECT,
    ARTIFACT_FILE_TYPE_PROMPT,
    ARTIFACT_FILE_TYPE_MISC,
)

KIND_COUNT_ORDER = (
    ARTIFACT_KIND_AGENT,
    ARTIFACT_KIND_BEAD,
    ARTIFACT_KIND_THOUGHT,
    ARTIFACT_KIND_COMMIT,
    ARTIFACT_KIND_CHANGESPEC,
    ARTIFACT_KIND_PROJECT,
    ARTIFACT_KIND_DIRECTORY,
    ARTIFACT_KIND_ROOT,
    ARTIFACT_KIND_UNKNOWN,
)

_KNOWN_STATES = {"ok", "missing", "loading", "stale", "error"}
_OK_STYLE = "#87D7AF"
_COUNT_STYLE = "#D7AF5F"
_UNAVAILABLE_STYLE = "dim"
_ERROR_STYLE = "dim #D75F5F"


@dataclass(frozen=True, slots=True)
class _ArtifactIndicatorCount:
    artifact_type: str
    total_count: int


@dataclass(frozen=True, slots=True)
class ArtifactIndicator:
    artifact_id: str
    state: ArtifactIndicatorState
    total_count: int = 0
    file_type_counts: tuple[_ArtifactIndicatorCount, ...] = ()
    kind_counts: tuple[_ArtifactIndicatorCount, ...] = ()
    error: str | None = None

    @classmethod
    def from_wire(cls, summary: ArtifactSummaryWire) -> ArtifactIndicator:
        state = _normalize_state(summary.state)
        return cls(
            artifact_id=summary.artifact_id,
            state=state,
            total_count=max(0, int(summary.total_linked_count)),
            file_type_counts=_ordered_counts(
                summary.file_type_counts,
                FILE_TYPE_COUNT_ORDER,
            ),
            kind_counts=_ordered_counts(summary.kind_counts, KIND_COUNT_ORDER),
            error=summary.error,
        )

    @property
    def render_signature(self) -> tuple[object, ...]:
        """Stable, compact value for future row render-cache keys."""

        return (
            self.artifact_id,
            self.state,
            self.total_count,
            tuple(
                (count.artifact_type, count.total_count)
                for count in self.file_type_counts
            ),
            tuple(
                (count.artifact_type, count.total_count) for count in self.kind_counts
            ),
            self.error or "",
        )


def artifact_indicator_from_summary(
    summary: ArtifactSummaryWire | None,
    artifact_id: str | None = None,
    *,
    loading: bool = False,
    stale: bool = False,
    error: str | None = None,
) -> ArtifactIndicator | None:
    """Build a row indicator from cached summary state.

    ``summary=None`` means no known artifact state yet unless a caller asks for a
    loading, stale, or error placeholder. That lets CL and Agent renderers share
    this helper without doing cache or facade work in row formatting.
    """

    if summary is not None:
        return ArtifactIndicator.from_wire(summary)
    if artifact_id is None:
        return None
    if error is not None:
        return ArtifactIndicator(artifact_id=artifact_id, state="error", error=error)
    if loading:
        return ArtifactIndicator(artifact_id=artifact_id, state="loading")
    if stale:
        return ArtifactIndicator(artifact_id=artifact_id, state="stale")
    return None


def render_artifact_indicator(indicator: ArtifactIndicator | None) -> Text:
    if indicator is None:
        return Text("")
    if indicator.state == "ok":
        if indicator.total_count <= 0:
            return Text("")
        return _render_ok_indicator(indicator)
    if indicator.state == "error":
        return Text("art !", style=_ERROR_STYLE)
    return Text("art ?", style=_UNAVAILABLE_STYLE)


def artifact_indicator_width(indicator: ArtifactIndicator | None) -> int:
    return render_artifact_indicator(indicator).cell_len


def _render_ok_indicator(indicator: ArtifactIndicator) -> Text:
    text = Text("art", style=_OK_STYLE)
    text.append(f" {indicator.total_count}", style=_OK_STYLE)
    for count in (*indicator.file_type_counts, *indicator.kind_counts):
        if count.total_count <= 0:
            continue
        text.append(f" {count.artifact_type}{count.total_count}", style=_COUNT_STYLE)
    return text


def _normalize_state(state: str) -> ArtifactIndicatorState:
    if state in _KNOWN_STATES:
        return state  # type: ignore[return-value]
    return "error"


def _ordered_counts(
    counts: list[ArtifactTypeCountWire],
    preferred_order: tuple[str, ...],
) -> tuple[_ArtifactIndicatorCount, ...]:
    totals: dict[str, int] = {}
    for count in counts:
        artifact_type = count.artifact_type.strip()
        if not artifact_type:
            continue
        total_count = max(0, int(count.total_count))
        if total_count <= 0:
            continue
        totals[artifact_type] = totals.get(artifact_type, 0) + total_count

    preferred_index = {value: index for index, value in enumerate(preferred_order)}

    def sort_key(item: tuple[str, int]) -> tuple[int, int | str]:
        artifact_type, _ = item
        index = preferred_index.get(artifact_type)
        if index is not None:
            return (0, index)
        return (1, artifact_type)

    return tuple(
        _ArtifactIndicatorCount(artifact_type=artifact_type, total_count=total_count)
        for artifact_type, total_count in sorted(totals.items(), key=sort_key)
    )


__all__ = [
    "ArtifactIndicator",
    "ArtifactIndicatorState",
    "FILE_TYPE_COUNT_ORDER",
    "KIND_COUNT_ORDER",
    "artifact_indicator_from_summary",
    "artifact_indicator_width",
    "render_artifact_indicator",
]
