"""Meaning and cause rows for the pager time band.

Owns the past meaning row (with SHA→agent→bead→section shedding) and the
instruction-file cause row, plus the target, source-join, and alias-chip
helpers used only by those two rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.pager._time_band_model import TimeBandData
from sase.pager._time_band_model import TimeBandTarget
from sase.pager._time_band_model import TimeBandVersion
from sase.pager._time_band_render_shared import honest_prefix
from sase.pager._time_band_render_shared import style_role
from sase.pager._time_band_vocab import ALIAS_SEPARATOR
from sase.pager._time_band_vocab import BAND_LABEL_STYLE
from sase.pager._time_band_vocab import CLASS_GLYPHS
from sase.pager._time_band_vocab import DIM_STYLE
from sase.pager._time_band_vocab import DIVERGED_CHIP
from sase.pager._time_band_vocab import PAST_STYLE
from sase.pager._time_band_vocab import UNCOMMITTED_STYLE


def meaning_row(
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
    past = style_role(styles, "past", PAST_STYLE)
    prefix = honest_prefix(data.honest_kind, data.honest_detail, styles)
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


def cause_row(
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
    prefix = honest_prefix(data.honest_kind, data.honest_detail)
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


def _glyph_for_class(class_name: str) -> str:
    """Return the band glyph for a core version class."""
    return CLASS_GLYPHS.get(class_name, "?")


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


__all__ = [
    "cause_row",
    "meaning_row",
]
