"""Shared glyph and style vocabulary for clan-wave list chrome."""

from rich.text import Text

from ..models._agent_clan_waves import ClanWaveSummary
from ._agent_list_styling import TREE_DEPTH_COLORS
from ._agent_list_render_rail import RAIL_FAILED_STYLE
from ..models.agent_status import RUNNING_COLOR
from ..agent_count_chip import AGENT_COUNT_CHIP_NEUTRAL_STYLE

WAVE_NUMBER_COLOR = TREE_DEPTH_COLORS[0]
WAVE_NUMBER_OPEN_STYLE = f"bold {WAVE_NUMBER_COLOR}"
WAVE_NUMBER_DONE_STYLE = f"dim {WAVE_NUMBER_COLOR}"
WAVE_UNRESOLVED_STYLE = "bold #FFAF00"
WAVE_BRACE_GLYPHS = ("╭", "├", "╰", "─")
WAVE_LANE_GLYPH = "│"
WAVE_GUTTER_WIDTH = 5

_WAVE_PIP_STYLES = {
    "failed": ("✗", RAIL_FAILED_STYLE),
    "needs_you": ("▲", "bold #FFAF00"),
    "in_flight": ("◐", f"bold {RUNNING_COLOR}"),
    "done": ("●", "#5FD75F"),
    "not_started": ("○", AGENT_COUNT_CHIP_NEUTRAL_STYLE),
    "dismissed_only": ("·", f"dim {AGENT_COUNT_CHIP_NEUTRAL_STYLE}"),
}
_WAVE_STATE_PRIORITY = (
    "failed",
    "needs_you",
    "in_flight",
    "done",
    "not_started",
    "dismissed_only",
)


def format_clan_wave_pips(summary: ClanWaveSummary | None) -> Text:
    """Render the compact wave-state strip for a layered clan."""
    text = Text()
    if summary is None or not summary.layered:
        return text

    numbered = tuple(wave for wave in summary.waves if wave.kind == "number")
    if len(numbered) > 12:
        states = {wave.state.value for wave in numbered}
        worst_state = next(state for state in _WAVE_STATE_PRIORITY if state in states)
        glyph, style = _WAVE_PIP_STYLES[worst_state]
        completed = sum(wave.state.value == "done" for wave in numbered)
        text.append(f"{glyph} {completed}/{summary.numbered_wave_count}", style=style)
    else:
        for wave in numbered:
            glyph, style = _WAVE_PIP_STYLES[wave.state.value]
            text.append(glyph, style=style)

    if summary.has_seal:
        seal = next(wave for wave in summary.waves if wave.kind == "seal")
        glyph, style = _WAVE_PIP_STYLES[seal.state.value]
        text.append(" ")
        text.append("∎", style=style)
    return text


def wave_connector_style(*, is_selected: bool) -> str:
    """Return the depth-one connector style used by a selected row."""
    return f"bold {WAVE_NUMBER_COLOR}" if is_selected else WAVE_NUMBER_COLOR


__all__ = [
    "WAVE_BRACE_GLYPHS",
    "WAVE_GUTTER_WIDTH",
    "WAVE_LANE_GLYPH",
    "WAVE_NUMBER_COLOR",
    "WAVE_NUMBER_DONE_STYLE",
    "WAVE_NUMBER_OPEN_STYLE",
    "WAVE_UNRESOLVED_STYLE",
    "format_clan_wave_pips",
    "wave_connector_style",
]
