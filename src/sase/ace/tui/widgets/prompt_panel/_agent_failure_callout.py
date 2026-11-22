"""Shared NEEDS ATTENTION callout for failed session, clan, and tribe panels."""

from __future__ import annotations

from rich.text import Text

from sase.monitor_state import NOT_ADOPTED_COLOR, NOT_ADOPTED_GLYPH

from ...models.failure_focus import FailureFocus

_FAILURE_BAR = "┃"
_FAILURE_BAR_STYLE = "#FF5F5F"
_FAILURE_HEADER_STYLE = "bold #FF5F5F"
_FAILURE_CAUSE_LABEL_STYLE = "dim #FF5F5F"
_FAILURE_CAUSE_CHIP_FALLBACK_STYLE = "bold #FF5F5F"
_FAILURE_BODY_STYLE = "#D7D7AF"
_FAILURE_COMMAND_STYLE = "bold #D7D7AF"
_FAILURE_DIM_STYLE = "dim"
_FAILURE_NEXT_LABEL_STYLE = "bold #FF5F5F"

_MAX_CALLOUT_LINES = 6


def _stop_time_label(focus: FailureFocus) -> str | None:
    """Return the failed turn's stop time as HH:MM:SS, if known."""
    stop = focus.failed_row.stop_time
    if stop is None:
        return None
    return stop.strftime("%H:%M:%S")


def format_failure_where_clan(agent: object, focus: FailureFocus) -> str:
    """Return the clan callout header location, e.g. ``wave 3 stopped at .8``."""
    label = focus.member_label or focus.failed_row.name
    waves = getattr(agent, "clan_waves", None)
    wave_phrase: str | None = None
    if waves is not None:
        try:
            failed_wave = next(
                wave for wave in waves.waves if wave.state.value == "failed"
            )
        except StopIteration:
            failed_wave = None
        if failed_wave is not None:
            if failed_wave.kind == "seal":
                wave_phrase = "land"
            elif failed_wave.kind == "unresolved":
                wave_phrase = "unresolved members"
            elif failed_wave.number is not None:
                wave_phrase = f"wave {failed_wave.number}"
    if wave_phrase is None:
        return f"stopped at {label}"
    return f"{wave_phrase} stopped at {label}"


def format_failure_where_session(focus: FailureFocus) -> str:
    """Return the session callout header location, e.g. ``turn .8 failed``."""
    label = focus.member_label or focus.failed_row.name
    if label:
        return f"turn {label} failed"
    return "session failed"


def append_failure_callout(
    text: Text,
    focus: FailureFocus,
    *,
    where: str,
    jump_number: str | None = None,
) -> None:
    """Append a left-barred NEEDS ATTENTION block for one failure focus.

    At most six lines: header, failed-turn cause, held-handoff cause,
    blocks, readopt next step, and jump/retry/dismiss hints. No free-text
    error parsing; the full error stays in the existing ERROR section.
    """
    lines: list[Text] = []

    header = Text()
    header.append(f"{_FAILURE_BAR} ", style=_FAILURE_BAR_STYLE)
    header.append("✗ NEEDS ATTENTION", style=_FAILURE_HEADER_STYLE)
    header.append(f" · {where}", style=_FAILURE_DIM_STYLE)
    lines.append(header)

    failed_line = Text()
    failed_line.append(f"{_FAILURE_BAR}   ", style=_FAILURE_BAR_STYLE)
    label = focus.member_label or focus.failed_row.name
    failed_line.append(label, style=_FAILURE_CAUSE_LABEL_STYLE)
    failed_line.append("  ", style=_FAILURE_DIM_STYLE)
    failed_line.append(focus.failed_row.name, style=_FAILURE_BODY_STYLE)
    failed_line.append(" failed", style=_FAILURE_BODY_STYLE)
    stop_label = _stop_time_label(focus)
    if stop_label is not None:
        failed_line.append(f" {stop_label}", style=_FAILURE_DIM_STYLE)
    chip = focus.finalizer_chip
    if chip:
        failed_line.append(" · ", style=_FAILURE_DIM_STYLE)
        failed_line.append(
            chip, style=focus.finalizer_chip_style or _FAILURE_CAUSE_CHIP_FALLBACK_STYLE
        )
    else:
        failed_line.append(" · ", style=_FAILURE_DIM_STYLE)
        if focus.not_adopted is not None:
            failed_line.append(NOT_ADOPTED_GLYPH, style=f"bold {NOT_ADOPTED_COLOR}")
        else:
            failed_line.append("✗", style=_FAILURE_CAUSE_CHIP_FALLBACK_STYLE)
    if focus.extra_failed:
        failed_line.append(f" +{focus.extra_failed}", style=_FAILURE_CAUSE_LABEL_STYLE)
    lines.append(failed_line)

    if focus.not_adopted is not None:
        held = focus.not_adopted
        held_line = Text()
        held_line.append(f"{_FAILURE_BAR}   ", style=_FAILURE_BAR_STYLE)
        held_line.append(NOT_ADOPTED_GLYPH, style=f"bold {NOT_ADOPTED_COLOR}")
        held_line.append("   ", style=_FAILURE_DIM_STYLE)
        held_line.append(f"{held.kind} handoff not adopted", style=_FAILURE_BODY_STYLE)
        held_line.append(" · ", style=_FAILURE_DIM_STYLE)
        held_line.append(held.name, style=_FAILURE_BODY_STYLE)
        held_line.append(" never ran", style=_FAILURE_BODY_STYLE)
        lines.append(held_line)

    if focus.blocked:
        blocked_line = Text()
        blocked_line.append(f"{_FAILURE_BAR}   ", style=_FAILURE_BAR_STYLE)
        blocked_line.append("⤷   ", style=_FAILURE_DIM_STYLE)
        blocked_line.append(
            f"blocks {', '.join(focus.blocked)}", style=_FAILURE_BODY_STYLE
        )
        lines.append(blocked_line)

    if focus.not_adopted is not None and focus.not_adopted.starter_name:
        next_line = Text()
        next_line.append(f"{_FAILURE_BAR}   ", style=_FAILURE_BAR_STYLE)
        next_line.append("next  ", style=_FAILURE_NEXT_LABEL_STYLE)
        next_line.append("repair the cause, then  ", style=_FAILURE_BODY_STYLE)
        next_line.append(
            f"sase agent readopt {focus.not_adopted.starter_name}",
            style=_FAILURE_COMMAND_STYLE,
        )
        lines.append(next_line)
    else:
        next_line = Text()
        next_line.append(f"{_FAILURE_BAR}   ", style=_FAILURE_BAR_STYLE)
        next_line.append("next  ", style=_FAILURE_NEXT_LABEL_STYLE)
        next_line.append("see ERROR below for details", style=_FAILURE_BODY_STYLE)
        lines.append(next_line)

    hints_line = Text()
    hints_line.append(f"{_FAILURE_BAR}         ", style=_FAILURE_BAR_STYLE)
    hints: list[tuple[str, str]] = []
    if jump_number is not None:
        hints.append((f"jump {jump_number}", _FAILURE_BODY_STYLE))
    hints.append(("R retry", _FAILURE_BODY_STYLE))
    hints.append(("x dismiss", _FAILURE_BODY_STYLE))
    for index, (hint, style) in enumerate(hints):
        if index:
            hints_line.append(" · ", style=_FAILURE_DIM_STYLE)
        hints_line.append(hint, style=style)
    lines.append(hints_line)

    for line in lines[:_MAX_CALLOUT_LINES]:
        text.append_text(line)
        text.append("\n")
    text.append("\n")


__all__ = [
    "append_failure_callout",
    "format_failure_where_clan",
    "format_failure_where_session",
]
