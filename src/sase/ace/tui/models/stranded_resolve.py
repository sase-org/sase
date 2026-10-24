"""Memory-only stranded-resolve view models.

Every field comes from the warm stranded-work cache. Callers that mount
:class:`~sase.ace.tui.modals.stranded_resolve_modal.StrandedResolveModal`
must not touch disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sase.bead.stranded_presentation import (
    stranded_age_label,
    stranded_cause_sentence,
)
from sase.core.stranded_work_facade import StrandedWorkVerdict

from .agent_stranded import cached_stranded_report

StrandedResolveChoice = Literal["continue", "close"]


@dataclass(frozen=True, slots=True)
class _StrandedResolveLeaf:
    """One stranded bead the modal can continue or close."""

    bead_id: str
    title: str
    kind: str
    last_turn: str | None
    ended_at_label: str
    cause: str
    age: str
    blocks: tuple[str, ...]
    continue_disabled_reason: str | None


@dataclass(frozen=True, slots=True)
class StrandedResolveView:
    """Facts for one resolve-modal mounting. No I/O."""

    project: str
    focus_id: str
    focus_state: str
    focus_kind: str
    focus_title: str
    focus_age: str
    generated_at: float
    leaves: tuple[_StrandedResolveLeaf, ...]
    selected_index: int = 0

    @property
    def selected_leaf(self) -> _StrandedResolveLeaf:
        """Return the currently highlighted leaf."""
        return self.leaves[self.selected_index]

    @property
    def title_kind(self) -> str:
        """Return ``phase``, ``epic``, or ``task`` for the modal title."""
        kind = self.focus_kind.strip() or "phase"
        if kind == "plan":
            return "epic"
        return kind


@dataclass(frozen=True, slots=True)
class StrandedResolveResult:
    """User choice from :class:`StrandedResolveModal`."""

    choice: StrandedResolveChoice
    project: str
    leaf_id: str


def _format_stranded_ended_at(since: float | None) -> str:
    """Return a host-independent ``Oct 22 06:28`` label, or ``""``."""
    if since is None:
        return ""
    stamp = datetime.fromtimestamp(since, tz=UTC)
    return stamp.strftime("%b %d %H:%M")


def blocking_line(blocks: tuple[str, ...]) -> str:
    """Return ``N beads · nearest … root`` from a leaf's ``blocks`` chain."""
    if not blocks:
        return ""
    count = len(blocks)
    noun = "bead" if count == 1 else "beads"
    nearest = blocks[0]
    root = blocks[-1]
    if count == 1 or nearest == root:
        return f"{count} {noun} · {nearest}"
    return f"{count} {noun} · {nearest} … {root}"


def _continue_stub(*, leaf_id: str, last_turn: str, cause: str) -> str:
    """Return the editable Continue prompt body from the plan mockup."""
    return (
        f"Continue stranded phase `{leaf_id}`: `{last_turn}` {cause}. "
        f"Re-read `sase bead read {leaf_id}` (notes included), finish the "
        "phase, and close it with `sase bead close`. If it must stay open, "
        "arm a monitor or gate before ending."
    )


def stranded_continue_prompt(
    *,
    leaf_id: str,
    last_turn: str,
    cause: str,
    vcs_tag: str | None = None,
    tab_name: str | None = None,
) -> str:
    """Prefill ``%id(bead=…) #fork:<last turn>`` plus the Continue stub."""
    stub = _continue_stub(leaf_id=leaf_id, last_turn=last_turn, cause=cause)
    prefix = f"%id(bead={leaf_id}) #fork:{last_turn} {stub}"
    if tab_name:
        prefix = f"%tab:{tab_name} {prefix}"
    if vcs_tag:
        prefix = f"{vcs_tag}{prefix}"
    return prefix


def _leaf_from_verdict(
    verdict: StrandedWorkVerdict,
    *,
    title: str,
    now: float,
) -> _StrandedResolveLeaf:
    last_turn = verdict.last_turn
    disabled = None if last_turn else "No last turn to fork"
    return _StrandedResolveLeaf(
        bead_id=verdict.bead_id,
        title=title,
        kind=verdict.kind,
        last_turn=last_turn,
        ended_at_label=_format_stranded_ended_at(verdict.since),
        cause=stranded_cause_sentence(verdict),
        age=stranded_age_label(verdict.since, now),
        blocks=verdict.blocks,
        continue_disabled_reason=disabled,
    )


def build_stranded_resolve_view(
    project: str,
    bead_id: str,
    *,
    selected_index: int = 0,
) -> StrandedResolveView | None:
    """Build a resolve view from the warm cache. Returns ``None`` if cold."""
    snapshot = cached_stranded_report(project)
    if snapshot is None:
        return None
    by_id = {verdict.bead_id: verdict for verdict in snapshot.report.verdicts}
    focus = by_id.get(bead_id)
    if focus is None or focus.state not in {"stranded", "blocked"}:
        return None
    leaf_ids: tuple[str, ...]
    if focus.state == "stranded":
        leaf_ids = (focus.bead_id,)
    else:
        leaf_ids = focus.blocked_by or ()
        if not leaf_ids:
            return None
    leaves: list[_StrandedResolveLeaf] = []
    for leaf_id in leaf_ids:
        verdict = by_id.get(leaf_id)
        if verdict is None:
            continue
        title = snapshot.titles.get(leaf_id) or ""
        leaves.append(
            _leaf_from_verdict(verdict, title=title, now=snapshot.generated_at)
        )
    if not leaves:
        return None
    index = max(0, min(selected_index, len(leaves) - 1))
    focus_title = snapshot.titles.get(focus.bead_id) or leaves[0].title
    return StrandedResolveView(
        project=project,
        focus_id=focus.bead_id,
        focus_state=focus.state,
        focus_kind=focus.kind,
        focus_title=focus_title,
        focus_age=stranded_age_label(focus.since, snapshot.generated_at),
        generated_at=snapshot.generated_at,
        leaves=tuple(leaves),
        selected_index=index,
    )


__all__ = [
    "StrandedResolveChoice",
    "StrandedResolveResult",
    "StrandedResolveView",
    "blocking_line",
    "build_stranded_resolve_view",
    "stranded_continue_prompt",
]
