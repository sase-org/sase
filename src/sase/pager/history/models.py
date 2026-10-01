"""Generic history models for pager sections.

No memory-specific vocabulary or core query algorithm belongs here: this
package normalizes wire results into generic pager presentation records
that the memory provider fills in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

HistoryView = Literal["read", "diff"]


@dataclass(frozen=True, slots=True)
class VersionPin:
    """One pinned view of a section's subject at a version.

    ``ordinal`` 0 means the live worktree (``now``); positive ordinals
    are committed versions. ``commit``/``blob_oid`` are full hex strings
    when known. ``view`` selects the read body or its change; when
    ``view`` is ``diff``, ``compare_base`` names the base ordinal the
    read gutter was computed against.
    """

    subject_id: str
    ordinal: int
    selector: str
    commit: str | None = None
    blob_oid: str | None = None
    view: HistoryView = "read"
    compare_base: int | None = None

    @property
    def is_live(self) -> bool:
        """Return whether this pin is the live worktree rather than history."""
        return self.ordinal == 0

    @property
    def display(self) -> str:
        """Return the compact selector display (``now`` or ``vN``)."""
        if self.is_live:
            return "now"
        return f"v{self.ordinal}"


@dataclass(slots=True)
class SectionTimeState:
    """Mutable per-section history state, isolated across scopes."""

    provider_key: str
    subject_id: str
    scope_key: str
    loading: bool = False
    error: str | None = None
    status: str = "live"
    timeline: tuple[dict[str, object], ...] = ()
    visible_ordinals: tuple[int, ...] = ()
    current_pin: VersionPin | None = None
    live_section: object | None = None
    pending_intent: str | None = None
    generation: int = 0
    body_cache: dict[tuple[int, str], object] = field(default_factory=dict)
    comparison_cache: dict[tuple[int, int], object] = field(default_factory=dict)


def live_pin_for_subject(subject_id: str, *, selector: str = "now") -> VersionPin:
    """Return the live-worktree pin for *subject_id*."""
    return VersionPin(subject_id=subject_id, ordinal=0, selector=selector)


def committed_pin_for_ordinal(
    subject_id: str,
    ordinal: int,
    *,
    commit: str | None = None,
    blob_oid: str | None = None,
    view: HistoryView = "read",
    compare_base: int | None = None,
) -> VersionPin:
    """Return a committed-version pin for *ordinal*."""
    return VersionPin(
        subject_id=subject_id,
        ordinal=ordinal,
        selector=f"v{ordinal}",
        commit=commit,
        blob_oid=blob_oid,
        view=view,
        compare_base=compare_base,
    )


__all__ = [
    "HistoryView",
    "SectionTimeState",
    "VersionPin",
    "committed_pin_for_ordinal",
    "live_pin_for_subject",
]
