"""Human-facing text rendered by the BeadStaleCleanup gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of the persisted payload: ages are derived from the
pinned ``stale_as_of`` instant, never from a live clock, and project labels
come from :func:`sase.project_display_names.project_display_name_for`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sase.project_display_names import project_display_name_for

_BEAD_COLUMNS = ("Bead", "Project", "Age", "+1", "Size", "Title")


def parse_stale_cleanup_instant(value: str) -> datetime:
    """Parse one payload instant as a timezone-aware datetime.

    Uses the same ``Z`` → ``+00:00`` convention as :mod:`sase.bead.model`
    and :mod:`sase.bead.snooze_time`. A naive value is rejected so an age
    cannot silently depend on the host timezone.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"stale cleanup instant must be timezone-aware: {value!r}")
    return parsed


def stale_cleanup_project_label(project: str) -> str:
    """Return the user-facing project name for one payload project key."""
    return project_display_name_for(project)


def stale_cleanup_age_days(created_at: str, *, stale_as_of: str) -> int:
    """Return whole days from *created_at* to the pinned *stale_as_of* instant."""
    created = parse_stale_cleanup_instant(created_at)
    as_of = parse_stale_cleanup_instant(stale_as_of)
    return max(0, (as_of - created).days)


def stale_cleanup_created_date(created_at: str) -> str:
    """Return the ISO date of *created_at* in its own offset."""
    return parse_stale_cleanup_instant(created_at).date().isoformat()


def render_bead_stale_cleanup_preview(payload: Any) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients.

    The body is a heading, one sentence naming the three thresholds, a table
    of the offered roster, and an omitted-count footer when the roster was
    truncated. Nothing agent-authored reaches it.
    """
    beads: Sequence[Any] = payload.beads
    min_plus_ones = payload.min_plus_ones
    stale_after_days = payload.stale_after_days
    stale_cleanup_min_beads = payload.stale_cleanup_min_beads
    omitted_count = payload.omitted_count
    stale_as_of = payload.stale_as_of
    plus_noun = "report" if min_plus_ones == 1 else "reports"
    day_noun = "day" if stale_after_days == 1 else "days"
    bead_noun = "bead" if stale_cleanup_min_beads == 1 else "beads"
    intro = (
        f"Ready task beads with fewer than {min_plus_ones} +1 {plus_noun} "
        f"for at least {stale_after_days} {day_noun} are eligible; this "
        f"gate is raised once at least {stale_cleanup_min_beads} such "
        f"{bead_noun} exist."
    )
    rows = [_preview_row(bead, stale_as_of=stale_as_of) for bead in beads]
    table = _markdown_table(_BEAD_COLUMNS, rows)
    footer = ""
    if omitted_count:
        omitted_noun = "bead" if omitted_count == 1 else "beads"
        footer = (
            f"\n\n{omitted_count} additional stale task {omitted_noun} "
            "were omitted from this roster."
        )
    return f"# Stale task beads\n\n{intro}\n\n{table}{footer}\n"


def bead_stale_cleanup_presentation_note(payload: Any) -> str:
    """Return the one-line notification note for one stale-cleanup gate."""
    count = len(payload.beads)
    noun = "bead" if count == 1 else "beads"
    min_plus_ones = payload.min_plus_ones
    days = payload.stale_after_days
    if min_plus_ones <= 1:
        bar = "no +1"
    else:
        bar = f"fewer than {min_plus_ones} +1"
    return f"{count} stale task {noun} · {bar} after {days} days"


def _preview_row(bead: Any, *, stale_as_of: str) -> tuple[str, ...]:
    created_at = _bead_attr(bead, "created_at")
    size = _bead_attr(bead, "size")
    return (
        str(_bead_attr(bead, "bead_id")),
        stale_cleanup_project_label(str(_bead_attr(bead, "project"))),
        f"{stale_cleanup_age_days(created_at, stale_as_of=stale_as_of)}d",
        str(_bead_attr(bead, "plus_one_count")),
        "" if size is None else str(size),
        str(_bead_attr(bead, "title")),
    )


def _bead_attr(bead: Any, name: str) -> Any:
    if isinstance(bead, Mapping):
        return bead[name]
    return getattr(bead, name)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_table_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _table_cell(value: str) -> str:
    return value.replace("\n", " ").replace("|", "\\|")


__all__ = [
    "bead_stale_cleanup_presentation_note",
    "parse_stale_cleanup_instant",
    "render_bead_stale_cleanup_preview",
    "stale_cleanup_age_days",
    "stale_cleanup_created_date",
    "stale_cleanup_project_label",
]
