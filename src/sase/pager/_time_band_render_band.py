"""Band orchestration plus life-strip, timeline, and tombstone rows.

Owns :func:`render_time_band` and the rows used only by it, with the
date-format, fit, honest-notice, scrubber, and marker helpers that no
other row module needs. Meaning and cause rows arrive as public imports
from :mod:`sase.pager._time_band_render_meaning`.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.pager._time_band_model import TimeBandData
from sase.pager._time_band_model import TimeBandVersion
from sase.pager._time_band_model import time_band_targets
from sase.pager._time_band_render_meaning import cause_row
from sase.pager._time_band_render_meaning import meaning_row
from sase.pager._time_band_render_shared import honest_prefix
from sase.pager._time_band_render_shared import style_role
from sase.pager._time_band_vocab import DELETED_STYLE
from sase.pager._time_band_vocab import DIM_STYLE
from sase.pager._time_band_vocab import UNCOMMITTED_STYLE
from sase.pager._time_band_vocab import render_scrubber


def render_time_band(
    data: TimeBandData,
    *,
    width: int,
    rows: int,
    hints: Mapping[int, str] | None = None,
    styles: Any | None = None,
) -> Text:
    """Render the band for *data*, clipped to *width* cells per row.

    *rows* is the budgeted row count from :func:`chrome_row_budget` (0–2).
    *hints* maps target indexes from :func:`time_band_targets` to their
    jump-hint capsules, painted before each target occurrence. *styles*
    is the theme-aware :class:`HistoryStyles` set; legacy constants apply
    without it.
    """
    width = max(0, int(width))
    rows = max(0, min(int(rows), 2))
    text = Text(no_wrap=True, overflow="crop")
    if width == 0 or rows == 0 or data.mode == "notice":
        if data.mode == "notice" and width and rows:
            return _fit_text(
                _honest_row_text(data.honest_kind, data.honest_detail), width
            )
        return text
    hint_map = dict(hints or {})
    if data.mode == "now" and not (data.view == "diff" and data.diff is not None):
        return _fit_text(_life_strip_row(data, width, styles), width)
    if data.mode == "now":
        # A diff view always shows the timeline row with its comparing
        # text and range-coloured scrubber, whatever the kind.
        if rows == 1:
            return _fit_text(_timeline_row(data, width, styles), width)
        text.append_text(_fit_text(_timeline_row(data, width, styles), width))
        text.append("\n")
        ordered = time_band_targets(data)
        text.append_text(
            _fit_text(meaning_row(data, ordered, hint_map, width, styles), width)
        )
        return text
    ordered = time_band_targets(data)
    if rows == 1:
        # Degraded past band: the meaning row survives, because the pill
        # already carries the identity. A deletion keeps its tombstone.
        if data.tombstone:
            return _fit_text(_tombstone_row(data, width, styles), width)
        if data.subject_kind == "instructions":
            return _fit_text(cause_row(data, ordered, hint_map, width), width)
        return _fit_text(meaning_row(data, ordered, hint_map, width, styles), width)
    text.append_text(_fit_text(_timeline_row(data, width, styles), width))
    text.append("\n")
    if data.tombstone:
        text.append_text(_fit_text(_tombstone_row(data, width, styles), width))
    elif data.subject_kind == "instructions":
        text.append_text(_fit_text(cause_row(data, ordered, hint_map, width), width))
    else:
        text.append_text(
            _fit_text(meaning_row(data, ordered, hint_map, width, styles), width)
        )
    return text


def _format_full(epoch: int) -> str:
    """Return a full absolute date and time (``Mon Aug 24 2026 12:41``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d %Y %H:%M")


def _format_day(epoch: int) -> str:
    """Return an absolute date without the time (``Tue Aug 25 2026``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%a %b %d %Y")


def _format_compact(epoch: int) -> str:
    """Return a compact absolute date and time (``Aug 24 2026 12:41``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d %Y %H:%M")


def _format_short(epoch: int) -> str:
    """Return a month-day date for diff bases (``Aug 24``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d")


def _honest_row_text(kind: str, detail: str | None) -> Text:
    """Render the one-row honest notice for states with no history."""
    text = Text(no_wrap=True, overflow="crop")
    if kind == "indexing":
        text.append("indexing…", style=DIM_STYLE)
    elif kind == "untracked":
        text.append("UNTRACKED", style=f"bold {UNCOMMITTED_STYLE}")
        text.append(" · commit this file to start its history", style=DIM_STYLE)
    elif kind == "ignored":
        text.append("IGNORED", style=f"bold {UNCOMMITTED_STYLE}")
    elif kind == "no_vcs":
        text.append("NO VCS", style=DIM_STYLE)
        text.append(" · home memory is not in git", style=DIM_STYLE)
    elif kind == "unavailable":
        reason = detail or "unknown reason"
        text.append(f"history unavailable: {reason}", style=DIM_STYLE)
    else:
        text.append("indexing…", style=DIM_STYLE)
    return text


def _fit_text(text: Text, width: int) -> Text:
    """Crop *text* to *width* cells with an ellipsis safety net."""
    if width <= 0:
        return Text(no_wrap=True, overflow="crop")
    if cell_len(text.plain) <= width:
        return text
    cropped = text.copy()
    plain = cropped.plain
    kept: list[str] = []
    used = 0
    for character in plain:
        size = cell_len(character)
        if used + size > max(width - 1, 0):
            break
        kept.append(character)
        used += size
    end = len("".join(kept))
    cropped = cropped[:end]
    cropped.append("…")
    return cropped


def _scrubber_args(
    data: TimeBandData,
    *,
    shown_ordinal: int | None,
    track_width: int,
    endpoints: str,
    styles: Any | None,
) -> dict[str, Any]:
    """Return the shared :func:`render_scrubber` arguments for *data*."""
    return {
        "ordinals": [version.ordinal for version in data.versions],
        "volumes": [version.volume for version in data.versions],
        "hidden": [bool(version.hidden) for version in data.versions],
        "deleted": [version.class_name == "deleted" for version in data.versions],
        "shown_ordinal": shown_ordinal,
        "view": data.view,
        "diff_base": data.diff[0] if data.diff is not None else None,
        "diff_target": data.diff[1] if data.diff is not None else None,
        "dirty": data.dirty,
        "tombstone": data.tombstone,
        "now_matches_newest": data.now_matches_newest,
        "track_width": track_width,
        "endpoints": endpoints,
        "styles": styles,
    }


def _who_text(data: TimeBandData, version: TimeBandVersion | None) -> str:
    """Return the ``agent.bead`` provenance owner for a life strip."""
    version = version if version is not None else data.newest
    if version is None:
        return ""
    if version.agent and version.bead:
        return f"{version.agent}.{version.bead}"
    return version.agent or version.bead or ""


def _version_by_ordinal(data: TimeBandData, ordinal: int) -> TimeBandVersion | None:
    """Return the band version for *ordinal*, if present."""
    for version in data.versions:
        if version.ordinal == ordinal:
            return version
    return None


def _life_strip_row(data: TimeBandData, width: int, styles: Any | None) -> Text:
    """Render the one-row life strip shown at now: scrubber plus history."""
    text = Text(no_wrap=True, overflow="crop")
    prefix = honest_prefix(data.honest_kind, data.honest_detail)
    if prefix is not None:
        text.append_text(prefix)
        text.append(" · ", style=DIM_STYLE)
    if not data.versions:
        text.append("no history yet", style=DIM_STYLE)
        return text
    who = _who_text(data, data.newest)
    when = ""
    if data.newest is not None and data.newest.committer_time:
        when = f"last changed {_format_day(data.newest.committer_time)}"
    # Shedding (§6.3): endpoint labels shed last. Drop the owner, then
    # the edits-not-durable notice, then the last-changed detail, then
    # the scrubber down to 8 cells, and only then the endpoint labels.
    show_who = True
    show_dirty = True
    show_when = True
    track_width = 60
    endpoint_mode = "full"
    while True:
        scrubber = render_scrubber(
            **_scrubber_args(
                data,
                shown_ordinal=None,
                track_width=track_width,
                endpoints=endpoint_mode,
                styles=styles,
            )
        )
        row = Text(no_wrap=True, overflow="crop")
        row.append_text(scrubber)
        if show_when and when:
            row.append(f"  {when}", style=DIM_STYLE)
            if show_who and who:
                row.append(f" · {who}", style=DIM_STYLE)
        if show_dirty and data.dirty:
            row.append("  ◌ edits not durable until committed", style=UNCOMMITTED_STYLE)
        if cell_len(row.plain) <= max(width, 0):
            text.append_text(row)
            return text
        if show_who:
            show_who = False
        elif show_dirty and data.dirty:
            show_dirty = False
        elif show_when and when:
            show_when = False
        elif track_width > 8:
            track_width = max(8, track_width - 12)
        elif endpoint_mode == "full":
            endpoint_mode = "short"
        elif endpoint_mode == "short":
            endpoint_mode = "none"
        else:
            text.append_text(row)
            return text


def _newer_text(data: TimeBandData) -> str:
    """Return the right-aligned ``N newer`` segment (``+ uncommitted`` dirty)."""
    if data.newer_count > 0 and data.dirty:
        return f"{data.newer_count} newer + uncommitted"
    if data.newer_count > 0:
        return f"{data.newer_count} newer"
    if data.dirty:
        return "+ uncommitted"
    return ""


def _upstream_text(data: TimeBandData) -> str:
    """Return the ``⇡N on origin/<branch>`` marker, or ``""``."""
    if not data.upstream_ahead:
        return ""
    marker = f"⇡{data.upstream_ahead}"
    if data.upstream_branch:
        marker = f"{marker} on {data.upstream_branch}"
    return marker


def _timeline_row(data: TimeBandData, width: int, styles: Any | None) -> Text:
    """Render the past timeline row: scrubber, date, subject, and markers.

    Shedding order: the commit subject, the ⇡N marker, ``N newer``, the
    weekday and time (the date stays), the scrubber down to 8 cells, and
    finally the endpoint labels.
    """
    text = Text(no_wrap=True, overflow="crop")
    version = data.current
    is_diff_early = data.view == "diff" and data.diff is not None
    if version is None and not is_diff_early:
        return text
    delete = style_role(styles, "delete", DELETED_STYLE)
    insert = style_role(styles, "insert", "green")
    is_diff = data.view == "diff" and data.diff is not None
    has_upstream = bool(_upstream_text(data))
    has_newer = bool(_newer_text(data))

    def middle_text(*, subject: bool, full_date: bool) -> Text:
        middle = Text(no_wrap=True, overflow="crop")
        if is_diff:
            base, target = data.diff or (0, 0)
            middle.append("comparing ", style=DIM_STYLE)
            if base > 0:
                base_version = _version_by_ordinal(data, base)
                middle.append(f"v{base}", style=f"bold {delete}")
                if base_version is not None and base_version.committer_time:
                    if data.dirty and target == 0:
                        when = _format_day(base_version.committer_time)
                    else:
                        when = _format_short(base_version.committer_time)
                    middle.append(f" {when}", style=f"bold {delete}")
                middle.append(" → ", style=DIM_STYLE)
            if target == 0:
                middle.append("uncommitted edits", style=insert)
            else:
                target_version = _version_by_ordinal(data, target)
                middle.append(f"v{target}", style=f"bold {insert}")
                if target_version is not None and target_version.committer_time:
                    when = _format_compact(target_version.committer_time)
                    middle.append(f" {when}", style=f"bold {insert}")
            return middle
        if version is None:
            return middle
        if version.committer_time:
            if full_date:
                middle.append(_format_full(version.committer_time), style=DIM_STYLE)
            else:
                day = datetime.datetime.fromtimestamp(version.committer_time).strftime(
                    "%b %d %Y"
                )
                middle.append(day, style=DIM_STYLE)
        if subject and data.commit_subject:
            if len(middle.plain):
                middle.append(" · ", style=DIM_STYLE)
            middle.append(data.commit_subject)
        return middle

    def right_text(*, newer: bool, upstream: bool) -> Text:
        right = Text(no_wrap=True, overflow="crop")
        if newer and has_newer:
            right.append(_newer_text(data), style=DIM_STYLE)
        if upstream and has_upstream:
            if len(right.plain):
                right.append("  ")
            right.append(_upstream_text(data), style=DIM_STYLE)
        return right

    show_subject = True
    show_upstream = True
    show_newer = True
    full_date = True
    track_width = 60
    endpoint_mode = "full"
    while True:
        if is_diff or version is None:
            shown_ordinal: int | None = None
        else:
            shown_ordinal = version.ordinal
        scrubber = render_scrubber(
            **_scrubber_args(
                data,
                shown_ordinal=shown_ordinal,
                track_width=track_width,
                endpoints=endpoint_mode,
                styles=styles,
            )
        )
        middle = middle_text(subject=show_subject, full_date=full_date)
        right = right_text(newer=show_newer, upstream=show_upstream)
        row = Text(no_wrap=True, overflow="crop")
        row.append_text(scrubber)
        if len(middle.plain):
            row.append("  ")
            row.append_text(middle)
        if len(right.plain):
            gap = max(max(width, 0) - cell_len(row.plain) - cell_len(right.plain), 1)
            row.append(" " * gap)
            row.append_text(right)
        if cell_len(row.plain) <= max(width, 0):
            text.append_text(row)
            return text
        if show_subject and not is_diff and data.commit_subject:
            show_subject = False
        elif show_upstream and has_upstream:
            show_upstream = False
        elif show_newer and has_newer:
            show_newer = False
        elif (
            full_date and not is_diff and version is not None and version.committer_time
        ):
            full_date = False
        elif track_width > 8:
            track_width = max(8, track_width - 8)
        elif endpoint_mode == "full":
            endpoint_mode = "short"
        elif endpoint_mode == "short":
            endpoint_mode = "none"
        else:
            text.append_text(row)
            return text


def _tombstone_row(data: TimeBandData, width: int, styles: Any | None) -> Text:
    """Render the deletion notice as chrome: date, actor, and last content."""
    del width
    text = Text(no_wrap=True, overflow="crop")
    version = data.current
    if version is None:
        return text
    delete = style_role(styles, "delete", DELETED_STYLE)
    if version.committer_time:
        when = _format_full(version.committer_time)
    else:
        when = "unknown date"
    actor = version.agent or version.author or "unknown"
    # The body shows the last content before the deletion, not the
    # tombstone itself.
    try:
        below = [v.ordinal for v in data.versions if v.ordinal < version.ordinal]
        last_content = max(below) if below else version.ordinal
    except Exception:
        last_content = version.ordinal
    text.append("✖ deleted ", style=f"bold {delete}")
    text.append(
        f"{when} by {actor} · showing last content (v{last_content})",
        style=DIM_STYLE,
    )
    return text


__all__ = [
    "render_time_band",
]
