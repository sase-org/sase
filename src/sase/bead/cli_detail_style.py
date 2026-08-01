"""Resolve and apply ``sase bead show`` detail styling levels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sase.ansi_style import ansi_sgr, apply_ansi
from sase.bead.cli_dep_render import resolve_color

_SECTION_COLOR = "#5F87FF"
_PATH_COLOR = "#87AFFF"
_TIER_COLOR = "#FFAF00"
_DANGLING_COLOR = "#FF8787"


class DetailStyle(StrEnum):
    """Resolved styling level for one ``render_issue_detail`` call.

    ``auto`` never survives resolution — :func:`resolve_detail_style` always
    returns one of these three concrete levels.
    """

    PLAIN = "plain"
    COLOR = "color"
    RICH = "rich"


def resolve_detail_style(*, style: str, color: str) -> DetailStyle:
    """Resolve ``--style``/``--color`` into one concrete :class:`DetailStyle`.

    ``--color`` is the gate deciding whether ANSI may be emitted at all;
    ``--style`` decides how much styling to apply once the gate is open. A
    closed gate always wins, regardless of the requested style.
    """
    if not resolve_color(color):
        return DetailStyle.PLAIN
    if style == "plain":
        return DetailStyle.PLAIN
    if style == "color":
        return DetailStyle.COLOR
    return DetailStyle.RICH


@dataclass(frozen=True)
class DetailPalette:
    """Additive ANSI accents for one resolved :class:`DetailStyle`.

    Every method returns *value* unchanged when the palette is disabled, so
    ``render_issue_detail`` can route every styling decision through one
    object instead of sprinkling ``if use_color:`` checks through the
    renderer.
    """

    enabled: bool

    @classmethod
    def for_style(cls, style: DetailStyle) -> DetailPalette:
        """Build the palette for *style*; ``PLAIN`` yields an inert palette."""
        return cls(enabled=style is not DetailStyle.PLAIN)

    def accent(self, value: str, style: str | None) -> str:
        """Apply a raw ANSI SGR escape already resolved by another module.

        Used for roles this palette does not own the color for: bead IDs,
        status glyphs/labels, type values, and phase sizes.
        """
        if not style:
            return value
        return apply_ansi(value, style, enabled=self.enabled)

    def title(self, value: str) -> str:
        """Style the bead title: bold, hueless."""
        return apply_ansi(value, ansi_sgr(bold=True), enabled=self.enabled)

    def section(self, value: str) -> str:
        """Style a top-level section header (``DESCRIPTION``, ``NOTES``, ...)."""
        return apply_ansi(
            value, ansi_sgr(color=_SECTION_COLOR, bold=True), enabled=self.enabled
        )

    def subsection(self, value: str) -> str:
        """Style a nested section header (``PHASES``, ``CHILD EPICS``)."""
        return apply_ansi(value, ansi_sgr(color=_SECTION_COLOR), enabled=self.enabled)

    def label(self, value: str) -> str:
        """Style a field label (``Type:``, ``Owner:``, ...)."""
        return apply_ansi(value, ansi_sgr(dim=True), enabled=self.enabled)

    def separator(self, value: str) -> str:
        """Style a connector glyph (``·``, ``→``, ``←``, ``↑``) or its text."""
        return apply_ansi(value, ansi_sgr(dim=True), enabled=self.enabled)

    def path(self, value: str) -> str:
        """Style a design/plan reference or REFS line."""
        return apply_ansi(value, ansi_sgr(color=_PATH_COLOR), enabled=self.enabled)

    def url(self, value: str) -> str:
        """Style a hosted-page or creator URL."""
        return apply_ansi(
            value, ansi_sgr(color=_PATH_COLOR, underline=True), enabled=self.enabled
        )

    def tier(self, value: str) -> str:
        """Style the ``epic``/``plan`` tier value."""
        return apply_ansi(value, ansi_sgr(color=_TIER_COLOR), enabled=self.enabled)

    def placeholder(self, value: str) -> str:
        """Style an absent-value placeholder (``(none)``, ``(unknown)``, ...)."""
        return apply_ansi(value, ansi_sgr(dim=True, italic=True), enabled=self.enabled)

    def dangling(self, value: str) -> str:
        """Style a ``(not found)`` marker on an unresolved bead reference."""
        return apply_ansi(value, ansi_sgr(color=_DANGLING_COLOR), enabled=self.enabled)


__all__ = ["DetailPalette", "DetailStyle", "resolve_detail_style"]
