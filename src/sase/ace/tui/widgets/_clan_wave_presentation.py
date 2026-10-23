"""Shared glyph and style vocabulary for clan-wave list chrome."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from ._agent_list_styling import TREE_DEPTH_COLORS
from ._agent_list_render_rail import RAIL_FAILED_STYLE
from ..models.agent_status import RUNNING_COLOR
from ..agent_count_chip import AGENT_COUNT_CHIP_NEUTRAL_STYLE

if TYPE_CHECKING:
    from ..models._agent_clan_waves import ClanWaveSummary

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


def format_clan_wave_pips(
    summary: ClanWaveSummary | None,
    *,
    stranded_member_keys: frozenset[str] = frozenset(),
) -> Text:
    """Render the compact wave-state strip for a layered clan."""
    text = Text()
    if summary is None or not summary.layered:
        return text

    numbered = tuple(wave for wave in summary.waves if wave.kind == "number")
    if len(numbered) > 12:
        states = {_wave_display_state(wave, stranded_member_keys) for wave in numbered}
        worst_state = next(state for state in _WAVE_STATE_PRIORITY if state in states)
        completed = sum(
            _wave_display_state(wave, stranded_member_keys) == "done"
            for wave in numbered
        )
        append_clan_wave_state_pip(text, worst_state)
        _glyph, style = _WAVE_PIP_STYLES[worst_state]
        text.append(f" {completed}/{summary.numbered_wave_count}", style=style)
    else:
        for wave in numbered:
            append_clan_wave_state_pip(
                text,
                _wave_display_state(wave, stranded_member_keys),
            )

    if summary.has_seal:
        seal = next(wave for wave in summary.waves if wave.kind == "seal")
        text.append(" ")
        append_clan_wave_state_pip(
            text,
            _wave_display_state(seal, stranded_member_keys),
            label="∎",
        )
    return text


def _wave_display_state(wave: object, stranded_member_keys: frozenset[str]) -> str:
    """Fold a stranded direct member into the existing needs-you wave state."""
    if stranded_member_keys.intersection(getattr(wave, "member_identities", ())):
        return "needs_you"
    state = getattr(wave, "state", None)
    return str(getattr(state, "value", "not_started"))


def append_clan_wave_state_pip(
    text: Text,
    state: str,
    *,
    label: str | None = None,
) -> None:
    """Append one state pip or wave label using the shared wave palette."""
    glyph, style = _WAVE_PIP_STYLES[state]
    text.append(glyph if label is None else label, style=style)


def wave_connector_style(*, is_selected: bool) -> str:
    """Return the depth-one connector style used by a selected row."""
    return f"bold {WAVE_NUMBER_COLOR}" if is_selected else WAVE_NUMBER_COLOR


def format_wave_after_phrase(
    *,
    kind: str,
    predecessor_labels: tuple[str, ...],
    predecessor_waves: tuple[int, ...],
    is_epic_seal: bool = False,
) -> str:
    """Return the shared ``after`` phrase for one wave or seal stage.

    The ladder and the roster share this helper so the same wave reads the
    same way on both surfaces. ``predecessor_labels`` holds the predecessor
    member labels in display order; ``predecessor_waves`` holds the sorted
    unique wave indices those predecessors sit in.
    """
    if kind == "unresolved":
        return "wait cycle"
    if kind == "seal":
        return "after every phase" if is_epic_seal else "after every member"
    if not predecessor_labels:
        return "no dependencies"
    if len(predecessor_labels) <= 3:
        return f"after {' '.join(predecessor_labels)}"
    waves = tuple(sorted(set(predecessor_waves)))
    if len(waves) == 1:
        return f"after wave {waves[0]}"
    if waves and waves == tuple(range(waves[0], waves[-1] + 1)):
        return f"after waves {waves[0]}–{waves[-1]}"
    if waves:
        return "after waves " + ", ".join(map(str, waves))
    return "after every member"


__all__ = [
    "WAVE_BRACE_GLYPHS",
    "WAVE_GUTTER_WIDTH",
    "WAVE_LANE_GLYPH",
    "WAVE_NUMBER_COLOR",
    "WAVE_NUMBER_DONE_STYLE",
    "WAVE_NUMBER_OPEN_STYLE",
    "WAVE_UNRESOLVED_STYLE",
    "append_clan_wave_state_pip",
    "format_clan_wave_pips",
    "format_wave_after_phrase",
    "wave_connector_style",
]
