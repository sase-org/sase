"""Row renderers for the pager time band.

Paints a :class:`sase.pager._time_band_model.TimeBandData` model into Rich
``Text`` rows: the one-row life strip at now, the meaning plus time rows in
the past, cause rows for instruction subjects, and honest-state notices.
The timeline model lives in :mod:`sase.pager._time_band_model` and shared
vocabulary in :mod:`sase.pager._time_band_vocab`.

Row plan (the band is the feature's signature visual):

- At now: a one-row life strip — sparkline, ``last changed …``, and
  ``◌ uncommitted`` when dirty.
- In the past: two rows — a meaning row (class glyph, section path, word
  delta, frontmatter semantics; bead, agent, short SHA on the right) and a
  time row (sparkline, absolute date, ``→ now``, dirty and upstream
  markers).
- Instruction subjects show a cause row instead of the meaning row.
- Honest states (untracked, ignored, no VCS, shallow, template, indexing,
  unavailable) render inside the band and never block the body: states
  with no usable history collapse the band to one honest row, while
  shallow/template annotate the normal rows.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping

from rich.cells import cell_len
from rich.text import Text

from sase.pager._time_band_model import TimeBandData
from sase.pager._time_band_model import TimeBandTarget
from sase.pager._time_band_model import TimeBandVersion
from sase.pager._time_band_model import time_band_targets
from sase.pager._time_band_vocab import ALIAS_SEPARATOR
from sase.pager._time_band_vocab import BAND_LABEL_STYLE
from sase.pager._time_band_vocab import CLASS_GLYPHS
from sase.pager._time_band_vocab import DIM_STYLE
from sase.pager._time_band_vocab import DIVERGED_CHIP
from sase.pager._time_band_vocab import PAST_STYLE
from sase.pager._time_band_vocab import UNCOMMITTED_STYLE
from sase.pager._time_band_vocab import format_age
from sase.pager._time_band_vocab import render_sparkline


def render_time_band(
    data: TimeBandData,
    *,
    width: int,
    rows: int,
    hints: Mapping[int, str] | None = None,
) -> Text:
    """Render the band for *data*, clipped to *width* cells per row.

    *rows* is the budgeted row count from :func:`chrome_row_budget` (0–2).
    *hints* maps target indexes from :func:`time_band_targets` to their
    jump-hint capsules, painted before each target occurrence.
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
    if data.mode == "now":
        return _fit_text(_life_strip_row(data, hint_map), width)
    ordered = time_band_targets(data)
    if rows == 1:
        # Degraded past band: the meaning row survives, the time row drops.
        if data.subject_kind == "instructions":
            return _fit_text(_cause_row(data, ordered, hint_map, width), width)
        return _fit_text(_meaning_row(data, ordered, hint_map, width), width)
    if data.subject_kind == "instructions":
        text.append_text(_fit_text(_cause_row(data, ordered, hint_map, width), width))
    else:
        text.append_text(_fit_text(_meaning_row(data, ordered, hint_map, width), width))
    text.append("\n")
    text.append_text(_fit_text(_time_row(data, width), width))
    return text


def _glyph_for_class(class_name: str) -> str:
    """Return the band glyph for a core version class."""
    return CLASS_GLYPHS.get(class_name, "?")


def _format_absolute(epoch: int) -> str:
    """Return an absolute local date and time (``Sep 22 2026 14:03``)."""
    return datetime.datetime.fromtimestamp(epoch).strftime("%b %d %Y %H:%M")


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


def _sparkline_for_data(data: TimeBandData, width: int) -> Text:
    """Render the life sparkline for *data* within *width* cells."""
    volumes = [version.volume for version in data.versions]
    classes = [version.class_name for version in data.versions]
    return render_sparkline(volumes, classes, data.spark_current, width)


def _who_text(data: TimeBandData, version: TimeBandVersion | None) -> str:
    """Return the ``agent.bead`` provenance owner for a life strip."""
    version = version if version is not None else data.newest
    if version is None:
        return ""
    if version.agent and version.bead:
        return f"{version.agent}.{version.bead}"
    return version.agent or version.bead or ""


def _life_strip_row(data: TimeBandData, hint_map: Mapping[int, str]) -> Text:
    """Render the one-row life strip shown at now."""
    del hint_map
    text = Text(no_wrap=True, overflow="crop")
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    if prefix is not None:
        text.append_text(prefix)
        text.append(" · ", style=DIM_STYLE)
    if data.newest is not None and data.newest.committer_time:
        age = format_age(data.now_epoch, data.newest.committer_time)
        who = _who_text(data, data.newest)
        spark = _sparkline_for_data(data, 24)
        text.append_text(spark)
        text.append(f"  last changed {age} ago", style=DIM_STYLE)
        if who:
            text.append(f" · {who}", style=DIM_STYLE)
    elif data.versions:
        text.append_text(_sparkline_for_data(data, 24))
        text.append("  no committed versions", style=DIM_STYLE)
    else:
        text.append("no history yet", style=DIM_STYLE)
    if data.dirty:
        text.append("  ◌ uncommitted", style=UNCOMMITTED_STYLE)
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
) -> Text:
    """Render the past meaning row with SHA→agent→bead→section shedding."""
    version = data.current
    text = Text(no_wrap=True, overflow="crop")
    if version is None:
        return text
    prefix = _honest_prefix(data.honest_kind, data.honest_detail)
    segments: list[Text] = []
    if prefix is not None:
        segments.append(prefix)
    glyph, summary = _meaning_text(version)
    left = Text(no_wrap=True, overflow="crop")
    left.append(f"{glyph} ", style=PAST_STYLE)
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
            sections_dropped.append(f"{glyph} ", style=PAST_STYLE)
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


def _time_row(data: TimeBandData, width: int) -> Text:
    """Render the past time row: sparkline, date, and trailing markers."""
    text = Text(no_wrap=True, overflow="crop")
    version = data.current
    if version is None:
        return text
    right = Text(no_wrap=True, overflow="crop")
    right.append("→ now", style=DIM_STYLE)
    if data.dirty:
        right.append(" ◌", style=UNCOMMITTED_STYLE)
    upstream: Text | None = None
    if data.upstream_ahead:
        upstream = Text(no_wrap=True, overflow="crop")
        marker = f"⇡{data.upstream_ahead}"
        if data.upstream_branch:
            marker = f"{marker} on {data.upstream_branch}"
        upstream.append(marker, style=DIM_STYLE)
    date = _format_absolute(version.committer_time) if version.committer_time else ""
    # Shedding order: the absolute date first, then the ⇡N marker.
    spark_room = max(width - cell_len(right.plain) - 4, 1)
    if date:
        date_piece = f"  {date}"
        if upstream is not None:
            probe = f"{date_piece}  {upstream.plain}"
        else:
            probe = date_piece
        if len(data.versions) + cell_len(probe) + cell_len(right.plain) + 4 <= width:
            spark_room = max(width - cell_len(probe) - cell_len(right.plain) - 4, 1)
        else:
            date = ""
    spark_width = min(len(data.versions), spark_room)
    text.append_text(_sparkline_for_data(data, max(spark_width, 1)))
    if date:
        text.append(f"  {date}", style=DIM_STYLE)
    rest = width - cell_len(text.plain) - cell_len(right.plain)
    if upstream is not None and cell_len(upstream.plain) + 3 <= rest:
        text.append("  ")
        text.append_text(upstream)
        rest = width - cell_len(text.plain) - cell_len(right.plain)
    text.append(" " * max(rest, 1))
    text.append_text(right)
    return text


__all__ = [
    "render_time_band",
]
