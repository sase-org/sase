"""Accessible Rich presentation helpers for a task bead's ``task_type`` slug.

Mirrors :mod:`sase.bead_type_presentation`, but resolves an open,
plugin-extensible set rather than a fixed enum, following the D6 read-authority
order: the live registry first, the committed snapshot next, and a degraded
``unknown`` presentation last. An empty slug is ``untyped`` (D8) -- a
presentation label, never a catalog member.

This is the only place any surface may derive a task-type glyph, accent, chip,
or CLI cell; every consumer routes through here rather than re-deriving
presentation from a ``TaskTypeRecord`` or the snapshot directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from sase.ansi_style import ANSI_RESET as _ANSI_RESET
from sase.ansi_style import ansi_sgr, xterm256_foreground_style
from sase.task_types._snapshot import task_type_snapshot_entry
from sase.task_types.fields import UNTYPED_TASK_TYPE, issue_task_type_slug
from sase.task_types.registry import get_task_type_registry

#: Glyph shown for a legacy task bead that carries no ``task_type`` at all.
UNTYPED_TASK_TYPE_GLYPH = "·"

#: Glyph shown for a ``task_type`` this machine cannot resolve to a spec.
UNKNOWN_TASK_TYPE_GLYPH = "?"

#: Fallback glyph for a resolved type whose spec declares none.
DEFAULT_TASK_TYPE_GLYPH = "•"

#: Neutral gray used for both degraded presentations, distinct from every
#: reserved or palette-assigned task-type accent.
_DEGRADED_ACCENT_COLOR = "#6C6C6C"

_DEGRADED_CHIP_STYLE = "dim italic"


@dataclass(frozen=True)
class _TaskTypePresentation:
    """Cross-surface glyph, accent, and chip metadata for one task-type slug."""

    glyph: str
    accent_color: str
    chip_style: str
    label: str
    known: bool = True

    @property
    def rich_style(self) -> str:
        """Return the standard bold Rich style used for standalone glyphs."""
        return f"bold {self.accent_color}" if self.known else _DEGRADED_CHIP_STYLE

    @property
    def cli_style(self) -> str:
        """Return the ANSI SGR foreground code matching ``accent_color``."""
        if not self.known:
            return ansi_sgr(dim=True, italic=True)
        return xterm256_foreground_style(self.accent_color)


def task_type_presentation(slug: str) -> _TaskTypePresentation:
    """Resolve presentation for one stored ``task_type`` slug.

    Never raises: an empty slug is the dim ``untyped`` presentation, and a
    slug this machine cannot resolve through the live registry or the
    committed snapshot degrades to a dim ``unknown`` presentation that still
    names the slug, per D3 ("a missing plugin is never a read failure").
    """
    if not slug:
        return _TaskTypePresentation(
            glyph=UNTYPED_TASK_TYPE_GLYPH,
            accent_color=_DEGRADED_ACCENT_COLOR,
            chip_style=_DEGRADED_CHIP_STYLE,
            label=UNTYPED_TASK_TYPE,
            known=False,
        )

    record = get_task_type_registry().by_slug.get(slug)
    if record is not None:
        accent = record.resolved_accent_color or _DEGRADED_ACCENT_COLOR
        return _TaskTypePresentation(
            glyph=record.resolved_glyph or DEFAULT_TASK_TYPE_GLYPH,
            accent_color=accent,
            chip_style=f"bold black on {accent}",
            label=str(record.spec.get("label") or record.task_type),
            known=True,
        )

    snapshot_entry = task_type_snapshot_entry(slug)
    if snapshot_entry is not None:
        accent = str(snapshot_entry.get("accent_color") or "") or _DEGRADED_ACCENT_COLOR
        glyph = str(snapshot_entry.get("glyph") or "") or DEFAULT_TASK_TYPE_GLYPH
        return _TaskTypePresentation(
            glyph=glyph,
            accent_color=accent,
            chip_style=f"bold black on {accent}",
            label=str(snapshot_entry.get("label") or slug),
            known=True,
        )

    return _TaskTypePresentation(
        glyph=UNKNOWN_TASK_TYPE_GLYPH,
        accent_color=_DEGRADED_ACCENT_COLOR,
        chip_style=_DEGRADED_CHIP_STYLE,
        label=slug,
        known=False,
    )


def task_type_chip(slug: str, *, width: int | None = None) -> Text:
    """Return a literal task-type chip, honest about an unresolved slug."""
    presentation = task_type_presentation(slug)
    display_slug = issue_task_type_slug(slug)
    label = f" {presentation.glyph} {display_slug} "
    if width is not None:
        label = label.ljust(max(width, len(label)))
    return Text(
        label,
        style=presentation.chip_style,
        overflow="crop",
        no_wrap=True,
    )


def task_type_cli_cell(
    slug: str,
    *,
    use_color: bool,
    width: int | None = None,
) -> str:
    """Return the padded glyph-only task-type cell for compact CLI rows."""
    presentation = task_type_presentation(slug)
    cell = presentation.glyph
    if width is not None:
        padding = " " * max(width - cell_len(cell), 0)
    else:
        padding = ""
    if use_color:
        return f"{presentation.cli_style}{cell}{_ANSI_RESET}{padding}"
    return cell + padding


__all__ = [
    "DEFAULT_TASK_TYPE_GLYPH",
    "UNKNOWN_TASK_TYPE_GLYPH",
    "UNTYPED_TASK_TYPE_GLYPH",
    "task_type_chip",
    "task_type_cli_cell",
    "task_type_presentation",
]
