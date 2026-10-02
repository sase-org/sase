"""Row renderers for the pager time band.

Paints a :class:`sase.pager._time_band_model.TimeBandData` model into Rich
``Text`` rows: the one-row life strip at now, the timeline plus meaning
rows in the past, cause rows for instruction subjects, tombstone chrome
for deletions, and honest-state notices. The timeline model lives in
:mod:`sase.pager._time_band_model` and shared vocabulary (including the
playhead scrubber) in :mod:`sase.pager._time_band_vocab`.

Row plan (the band is the feature's signature visual):

- At now: a one-row life strip — scrubber, ``last changed …``, and
  ``◌ edits not durable until committed`` when dirty.
- In the past: two rows — a timeline row (playhead scrubber with
  labelled ends, absolute date, commit subject, ``N newer``, upstream
  marker) and a meaning row (class glyph, section path, word delta,
  frontmatter semantics; bead, agent, short SHA on the right) sitting
  directly above the body it describes. With one row only the meaning
  row is kept, because the pill already carries the identity.
- In the diff view the timeline row spells out the compared range and
  both endpoints (``Δ v23 → v24``), colour-matched to the body's delete
  and insert tones.
- Instruction subjects show a cause row instead of the meaning row; a
  deletion shows a tombstone row instead of the meaning row.
- Honest states (untracked, ignored, no VCS, shallow, template, indexing,
  unavailable) render inside the band and never block the body: states
  with no usable history collapse the band to one honest row, while
  shallow/template annotate the normal rows.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.pager._time_band_model import TimeBandData
from sase.pager._time_band_model import TimeBandTarget
from sase.pager._time_band_model import TimeBandVersion
from sase.pager._time_band_model import time_band_targets
from sase.pager._time_band_vocab import ALIAS_SEPARATOR
from sase.pager._time_band_vocab import BAND_LABEL_STYLE
from sase.pager._time_band_vocab import CLASS_GLYPHS
from sase.pager._time_band_vocab import DELETED_STYLE
from sase.pager._time_band_vocab import DIM_STYLE
from sase.pager._time_band_vocab import DIVERGED_CHIP
from sase.pager._time_band_vocab import PAST_STYLE
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
        text.append_text(
            _fit_text(_meaning_row(data, ordered, hint_map, width, styles), width)
        )
        return text
    ordered = time_band_targets(data)
    if rows == 1:
        # Degraded past band: the meaning row survives, because the pill
        # already carries the identity. A deletion keeps its tombstone.
        if data.tombstone:
            return _fit_text(_tombstone_row(data, width, styles), width)
        if data.subject_kind == "instructions":
            return _fit_text(_cause_row(data, ordered, hint_map, width), width)
        return _fit_text(_meaning_row(data, ordered, hint_map, width, styles), width)
    text.append_text(_fit_text(_timeline_row(data, width, styles), width))
    text.append("\n")
    if data.tombstone:
        text.append_text(_fit_text(_tombstone_row(data, width, styles), width))
    elif data.subject_kind == "instructions":
        text.append_text(_fit_text(_cause_row(data, ordered, hint_map, width), width))
    else:
        text.append_text(
            _fit_text(_meaning_row(data, ordered, hint_map, width, styles), width)
        )
    return text


def _glyph_for_class(class_name: str) -> str:
    """Return the band glyph for a core version class."""
    return CLASS_GLYPHS.get(class_name, "?")


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


def _style_role(styles: Any | None, attr: str, fallback: str) -> str:
    """Return one history colour role, falling back to legacy constants."""
    if styles is not None:
        try:
            value = getattr(styles, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value
    return fallback


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


def _honest_prefix(kind: str, detail: str | None) -> Text | None:
    """Return the leading honest segment for history-backed rows, if any."""
    if kind == "shallow":
        text = Text(no_wrap=True, overflow="crop")
        text.append("SHALLOW", style=DIM_STYLE)
        if detail:
            text.append(f" · history truncated at {detail}", style=DIM_STYLE)
        else:
            text.append(" · history truncated", style=DIM_STYLE)
        return text
    if kind == "template":
        text = Text(no_wrap=True, overflow="crop")
        text.append("TEMPLATE", style=DIM_STYLE)
        text.append(" · per-host rendering", style=DIM_STYLE)
        return text
    return None


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
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
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


def _meaning_text(version: TimeBandVersion) -> tuple[str, str]:
    """Return the ``(glyph, summary)`` left side for a meaning row."""
    glyph = _glyph_for_class(version.class_name)
    if version.class_name == "moved":
        old = version.source_path or version.path
        new = version.path or version.source_path
        if old and new and old != new:
            detail = f"↦ renamed {old} → {new}"
        else:
            detail = "↦ moved"
        if version.similarity is not None:
            detail = f"{detail} {version.similarity}%"
        return (glyph, detail)
    if version.class_name == "created":
        size = f" · {version.created_words}w" if version.created_words else ""
        sections = "".join(f" § {section}" for section in version.section_paths)
        return (glyph, f"created{sections}{size}")
    parts: list[str] = []
    if version.frontmatter_phrase:
        parts.append(version.frontmatter_phrase)
    parts.extend(f"§ {section}" for section in version.section_paths)
    words = _words_text(version)
    if words:
        parts.append(words)
    if not parts:
        parts.append(version.class_name)
    return (glyph, " · ".join(parts))


def _words_text(version: TimeBandVersion) -> str:
    """Return the word-delta suffix (``+31w -4w``) for a version."""
    if version.class_name == "created":
        return ""
    bits: list[str] = []
    if version.words_added:
        bits.append(f"+{version.words_added}w")
    if version.words_removed:
        bits.append(f"-{version.words_removed}w")
    return " ".join(bits)


def _meaning_row(
    data: TimeBandData,
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    width: int,
    styles: Any | None = None,
) -> Text:
    """Render the past meaning row with SHA→agent→bead→section shedding."""
    version = data.current
    text = Text(no_wrap=True, overflow="crop")
    if version is None:
        return text
    past = _style_role(styles, "past", PAST_STYLE)
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    segments: list[Text] = []
    if prefix is not None:
        segments.append(prefix)
    glyph, summary = _meaning_text(version)
    if data.path_at_version:
        summary = f"{summary} · as {data.path_at_version}"
    left = Text(no_wrap=True, overflow="crop")
    left.append(f"{glyph} ", style=past)
    left.append(summary)
    segments.append(left)
    # Right-side provenance in bead · agent · SHA order; shed SHA, agent,
    # bead, then the section path as width shrinks.
    right_bits: list[tuple[str, Text]] = []
    if version.bead:
        right_bits.append(
            ("bead", _target_text(ordered, hint_map, "bead", version.bead))
        )
    if version.agent:
        right_bits.append(
            ("agent", _target_text(ordered, hint_map, "agent", version.agent))
        )
    if version.commit:
        short = version.commit[:7]
        right_bits.append(("commit", _target_text(ordered, hint_map, "commit", short)))
    shed_sections = " § " in summary
    for shed in ("commit", "agent", "bead", "sections"):
        candidate = _join_meaning_row(segments, right_bits)
        if (
            cell_len(candidate.plain) <= max(width, 0)
            or not right_bits
            and shed != "sections"
        ):
            text.append_text(candidate)
            return text
        if shed == "sections" and shed_sections:
            sections_dropped = Text(no_wrap=True, overflow="crop")
            sections_dropped.append(f"{glyph} ", style=past)
            head = summary.split(" § ")[0].rstrip("· ")
            words = _words_text(version)
            sections_dropped.append(head + (f" · {words}" if words else ""))
            segments = ([prefix] if prefix is not None else []) + [sections_dropped]
            candidate = _join_meaning_row(segments, right_bits)
            text.append_text(candidate)
            return text
        right_bits = [bit for bit in right_bits if bit[0] != shed]
    candidate = _join_meaning_row(segments, right_bits)
    text.append_text(candidate)
    return text


def _join_meaning_row(segments: list[Text], right_bits: list[tuple[str, Text]]) -> Text:
    """Join meaning-row segments with a two-space gutter before provenance."""
    text = Text(no_wrap=True, overflow="crop")
    for index, segment in enumerate(segments):
        if index:
            text.append(" · ", style=DIM_STYLE)
        text.append_text(segment)
    if right_bits:
        text.append("  ")
        for index, (_, bit) in enumerate(right_bits):
            if index:
                text.append(" · ", style=DIM_STYLE)
            text.append_text(bit)
    return text


def _target_text(
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    kind: str,
    display: str,
) -> Text:
    """Render one band target display with its jump-hint capsule."""
    text = Text(no_wrap=True, overflow="crop")
    for index, target in enumerate(ordered):
        if target.kind == kind and target.display == display:
            hint = hint_map.get(index)
            if hint:
                text.append(f"[{hint}]", style=BAND_LABEL_STYLE)
            break
    text.append(display, style="bold")
    return text


def _cause_row(
    data: TimeBandData,
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
    width: int,
) -> Text:
    """Render the instruction-file cause row replacing the meaning row."""
    version = data.current
    text = Text(no_wrap=True, overflow="crop")
    if version is None:
        return text
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    if prefix is not None:
        text.append_text(prefix)
        text.append(" · ", style=DIM_STYLE)
    if not data.managed:
        text.append("◆ hand-edited", style=DIM_STYLE)
    elif version.sources:
        text.append("⟳ rendered", style=DIM_STYLE)
        text.append(" · sources: ", style=DIM_STYLE)
        shown = list(version.sources)
        while shown:
            candidate = _join_sources(shown, ordered, hint_map)
            if cell_len(text.plain) + cell_len(candidate.plain) <= max(width, 0):
                text.append_text(candidate)
                break
            shown = shown[:-1]
        if not shown:
            text.append("…", style=DIM_STYLE)
    elif version.config_paths:
        text.append("⚙ config change", style=DIM_STYLE)
        for path in version.config_paths:
            piece = Text(no_wrap=True, overflow="crop")
            piece.append(" · ", style=DIM_STYLE)
            piece.append(path, style="bold")
            if cell_len(text.plain) + cell_len(piece.plain) > max(width, 0):
                break
            text.append_text(piece)
    else:
        text.append("⚙ regenerated", style=DIM_STYLE)
        text.append(
            " · no source change in this commit (likely a sase upgrade)",
            style=DIM_STYLE,
        )
    chip = _alias_chip(data, version)
    if chip is not None and cell_len(text.plain) + cell_len(chip.plain) + 3 <= max(
        width, 0
    ):
        text.append(" · ", style=DIM_STYLE)
        text.append_text(chip)
    return text


def _join_sources(
    shown: list[tuple[str, str]],
    ordered: tuple[TimeBandTarget, ...],
    hint_map: Mapping[int, str],
) -> Text:
    """Join cause source displays with their hint capsules."""
    text = Text(no_wrap=True, overflow="crop")
    for index, (_subject_id, display) in enumerate(shown):
        if index:
            text.append(", ", style=DIM_STYLE)
        text.append_text(_target_text(ordered, hint_map, "source", display))
    return text


def _alias_chip(data: TimeBandData, version: TimeBandVersion) -> Text | None:
    """Return the ``≡ AGENTS.md`` / ``⚠ diverged`` chip, if any."""
    if data.subject_kind != "instructions":
        return None
    if version.diverged:
        return Text(DIVERGED_CHIP, style=UNCOMMITTED_STYLE)
    if version.aliased_paths:
        alias = version.aliased_paths[0].replace("\\", "/").rsplit("/", 1)[-1]
        canonical = (version.path.replace("\\", "/").rsplit("/", 1)[-1]) or "AGENTS.md"
        if alias and alias != canonical:
            return Text(f"{alias} {ALIAS_SEPARATOR} {canonical}", style=DIM_STYLE)
    return None


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
    delete = _style_role(styles, "delete", DELETED_STYLE)
    insert = _style_role(styles, "insert", "green")
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
        scrubber = render_scrubber(
            **_scrubber_args(
                data,
                shown_ordinal=None if is_diff else version.ordinal,
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
        elif full_date and not is_diff and version.committer_time:
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
    delete = _style_role(styles, "delete", DELETED_STYLE)
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
