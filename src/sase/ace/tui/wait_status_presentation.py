"""Shared sase's TUI presentation for wait dependency statuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    AGENT_STATUS_BUCKETS,
    QUEUED_STATUS_COLOR,
)
from sase.bead_status_presentation import (
    BEAD_STATUS_PRESENTATIONS,
    bead_status_presentation,
)

if TYPE_CHECKING:
    from ._agent_completion_wait import (
        WaitDependencyStatusCounts,
    )


@dataclass(frozen=True, slots=True)
class _WaitStatusBadge:
    """Glyph and Rich style for one compact wait-status badge."""

    glyph: str
    style: str


WAIT_UNKNOWN_GLYPH = "?"
WAIT_UNKNOWN_GLYPH_STYLE = "bold #FFAF5F"
WAIT_UNRESOLVABLE_GLYPH = "!"
WAIT_UNRESOLVABLE_GLYPH_STYLE = "bold #FF5F5F"
WAIT_BEAD_ID_STYLE = "#FF87D7"

# Teal `↪` hand-off for `%wait(for_epic=)` follows: the same teal as
# `EPIC CREATED`. The pending `epic…` token stays dim; a resolved follow
# reuses the followed bead's own glyph and style.
FOLLOW_GLYPH = "↪"
FOLLOW_GLYPH_STYLE = "bold #5FD7AF"
FOLLOW_PENDING_STYLE = "dim #5FD7AF"
FOLLOW_PENDING_TEXT = "epic…"

# Glyphs mirror ``AGENT_STATUS_BUCKET_GLYPHS``; colors mirror the established
# agent-row status accents.
WAIT_STATUS_BADGES: dict[str, _WaitStatusBadge] = {
    "Running": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "Queued": _WaitStatusBadge(
        AGENT_STATUS_BUCKET_GLYPHS["Queued"],
        f"bold {QUEUED_STATUS_COLOR}",
    ),
    "Waiting": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
    "Starting": _WaitStatusBadge(
        AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"
    ),
    "Done": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "Failed": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Failed"], "bold #FF5F5F"),
    "Stopped": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Stopped"], "bold #8787AF"),
}

WAIT_UNKNOWN_BADGE = _WaitStatusBadge(WAIT_UNKNOWN_GLYPH, WAIT_UNKNOWN_GLYPH_STYLE)
WAIT_STATUS_COUNT_BUCKETS: tuple[str, ...] = AGENT_STATUS_BUCKETS
WAIT_AGENT_BUCKET_TO_BEAD_STATUS: dict[str, str] = {
    "Starting": "claimed",
    "Running": "in_progress",
    "Waiting": "open",
    "Done": "closed",
    "unknown": "unknown",
}


def _wait_status_badge(bucket: str | None) -> _WaitStatusBadge:
    """Return the wait badge for a normalized agent bucket or unknown value."""
    if bucket is None:
        return WAIT_UNKNOWN_BADGE
    return WAIT_STATUS_BADGES.get(bucket, WAIT_UNKNOWN_BADGE)


def _wait_bead_status_token(status: str | None) -> tuple[str, str]:
    """Return the canonical status glyph and Rich style for a waited-on bead."""
    if status in BEAD_STATUS_PRESENTATIONS:
        presentation = bead_status_presentation(status)
        return (
            presentation.tui_glyph,
            presentation.rich_style,
        )
    return WAIT_UNKNOWN_GLYPH, WAIT_UNKNOWN_GLYPH_STYLE


def append_wait_status_badge(text: Text, bucket: str | None) -> None:
    """Append the standard per-target badge for a wait dependency."""
    badge = _wait_status_badge(bucket)
    text.append(" ")
    text.append(badge.glyph, style=badge.style)


def append_wait_bead_status_badge(text: Text, status: str | None) -> None:
    """Append the status-bearing bead wait token without a count."""
    token, style = _wait_bead_status_token(status)
    text.append(" ")
    text.append(token, style=style)


def _append_wait_agent_status_count(
    text: Text,
    bucket: str,
    count: int,
    *,
    leading_space: bool,
) -> None:
    """Append one compact agent wait-count token."""
    if leading_space:
        text.append(" ")
    badge = _wait_status_badge(None if bucket == "unknown" else bucket)
    text.append(f"{badge.glyph}{count}", style=badge.style)


def _append_wait_bead_status_count(
    text: Text,
    status: str,
    count: int,
    *,
    leading_space: bool,
) -> None:
    """Append one compact bead wait-count token."""
    if leading_space:
        text.append(" ")
    token, style = _wait_bead_status_token(None if status == "unknown" else status)
    text.append(f"{token}{count}", style=style)


def _format_wait_dependency_status_counts(
    counts: WaitDependencyStatusCounts | None,
) -> Text:
    """Format a zero-suppressed compact wait dependency status-count summary."""
    rendered = Text()
    if counts is None or not counts.has_any:
        return rendered

    consumed_bead_statuses: set[str] = set()
    first = True
    for bucket, count in counts.agents.nonzero_buckets():
        _append_wait_agent_status_count(
            rendered,
            bucket,
            count,
            leading_space=not first,
        )
        first = False
        bead_status = WAIT_AGENT_BUCKET_TO_BEAD_STATUS.get(bucket)
        if bead_status is None:
            continue
        bead_count = counts.beads.count_for_status(bead_status)
        if bead_count <= 0:
            continue
        _append_wait_bead_status_count(
            rendered,
            bead_status,
            bead_count,
            leading_space=True,
        )
        consumed_bead_statuses.add(bead_status)

    for status, count in counts.beads.nonzero_statuses():
        if status in consumed_bead_statuses:
            continue
        _append_wait_bead_status_count(
            rendered,
            status,
            count,
            leading_space=not first,
        )
        first = False
    return rendered


def append_epic_follow_tokens(
    text: Text,
    *,
    views: object = (),
    waiting_for: object = (),
    follows: object = None,
) -> None:
    """Append the compact `↪` epic-follow tokens for one WAITING row.

    Tokens sit after the existing agent/bead count tokens and before the
    `!` and time annotations. An armed target with no persisted stage adds
    no row noise. One followed epic names its bead ID; several epics reuse
    the follow-segment bead counts; a blocked follow reads `↪ !` in red;
    a launch in flight reads `↪ epic…` in dim teal. Pure in-memory
    formatting over the already-loaded views and counts: never touches the
    filesystem.
    """
    from sase.core.wait_epic_follow_view import epic_follow_views

    names = (
        set(waiting_for)
        if isinstance(waiting_for, (list, tuple, set, frozenset))
        else set()
    )
    active = [view for view in epic_follow_views(views) if view.target in names]
    launching = [view for view in active if view.state == "launching"]
    blocked = [view for view in active if view.state == "blocked"]
    epic_ids: list[str] = []
    for view in active:
        if view.state != "following":
            continue
        for epic_id in view.epic_ids:
            if epic_id not in epic_ids:
                epic_ids.append(epic_id)
    if epic_ids:
        text.append(" ")
        text.append(FOLLOW_GLYPH, style=FOLLOW_GLYPH_STYLE)
        if len(epic_ids) == 1:
            status = _sole_follow_status(follows)
            if status is not None:
                token, style = _wait_bead_status_token(
                    None if status == "unknown" else status
                )
                text.append(f" {token}", style=style)
            text.append(f" {epic_ids[0]}", style=WAIT_BEAD_ID_STYLE)
        elif _follows_has_any(follows):
            for status, count in _follow_nonzero_statuses(follows):
                token, style = _wait_bead_status_token(
                    None if status == "unknown" else status
                )
                text.append(f" {token}{count}", style=style)
        else:
            # Statuses still cold: a neutral count that claims no status.
            text.append(f" {len(epic_ids)}", style=FOLLOW_GLYPH_STYLE)
    elif launching:
        text.append(" ")
        text.append(FOLLOW_GLYPH, style=FOLLOW_GLYPH_STYLE)
        text.append(f" {FOLLOW_PENDING_TEXT}", style=FOLLOW_PENDING_STYLE)
    if blocked:
        text.append(" ")
        text.append(FOLLOW_GLYPH, style=FOLLOW_GLYPH_STYLE)
        text.append(" ")
        text.append(
            WAIT_UNRESOLVABLE_GLYPH,
            style=WAIT_UNRESOLVABLE_GLYPH_STYLE,
        )


def _sole_follow_status(follows: object) -> str | None:
    """Return the single follow-segment status for a one-epic row, if known."""
    statuses = _follow_nonzero_statuses(follows)
    if len(statuses) != 1:
        return None
    status, count = statuses[0]
    return status if count == 1 else None


def _follows_has_any(follows: object) -> bool:
    """Return whether a follow-segment count object has any counts."""
    has_any = getattr(follows, "has_any", None)
    if callable(has_any):
        try:
            return bool(has_any())
        except Exception:
            return False
    return bool(has_any)


def _follow_nonzero_statuses(follows: object) -> list[tuple[str, int]]:
    """Return the follow segment's nonzero statuses in canonical bead order."""
    iterator = getattr(follows, "nonzero_statuses", None)
    if not callable(iterator):
        return []
    try:
        return [(status, count) for status, count in iterator()]
    except Exception:
        return []


def _sole_bead_status(
    counts: WaitDependencyStatusCounts | None,
) -> str | None:
    """Return the sole counted bead status for a singleton wait, if unambiguous."""
    if counts is None or not counts.has_any:
        return None
    if counts.agents.has_any:
        return ""
    statuses = tuple(counts.beads.nonzero_statuses())
    if len(statuses) != 1:
        return ""
    status, count = statuses[0]
    return status if count == 1 else ""


def format_wait_dependency_summary(
    counts: WaitDependencyStatusCounts | None,
    *,
    single_bead_id: str | None = None,
) -> Text:
    """Format a wait dependency summary, optionally naming one waited-on bead."""
    if not single_bead_id:
        return _format_wait_dependency_status_counts(counts)

    sole_status = _sole_bead_status(counts)
    if sole_status == "":
        return _format_wait_dependency_status_counts(counts)

    rendered = Text()
    if sole_status is not None:
        token, style = _wait_bead_status_token(
            None if sole_status == "unknown" else sole_status
        )
        rendered.append(token, style=style)
        rendered.append(" ")
    rendered.append(single_bead_id, style=WAIT_BEAD_ID_STYLE)
    return rendered


__all__ = [
    "FOLLOW_GLYPH",
    "FOLLOW_GLYPH_STYLE",
    "FOLLOW_PENDING_STYLE",
    "FOLLOW_PENDING_TEXT",
    "WAIT_BEAD_ID_STYLE",
    "WAIT_STATUS_BADGES",
    "WAIT_STATUS_COUNT_BUCKETS",
    "WAIT_UNKNOWN_GLYPH",
    "WAIT_UNKNOWN_GLYPH_STYLE",
    "WAIT_UNRESOLVABLE_GLYPH",
    "WAIT_UNRESOLVABLE_GLYPH_STYLE",
    "append_epic_follow_tokens",
    "append_wait_bead_status_badge",
    "append_wait_status_badge",
    "format_wait_dependency_summary",
]
