"""Rich presentation helpers for SASE commit-footer tags."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

_TYPE_COLORS = {
    "stitch": "#FFD700",
    "sdd": "#87D7FF",
    "init": "#5FD75F",
    "beads": "#5FD7AF",
    "bead_work": "#00D7AF",
    "memory": "#AF87FF",
    "skills": "#D787AF",
    "xprompt": "#FFAF5F",
    "config": "#D7AF5F",
    "revert": "#D75F5F",
}
_TYPE_FALLBACK_COLOR = "#AF87D7"
_AGENT_COLOR = "#FFD700"
_BUG_COLOR = "#FF8787"
_PLAN_BASENAME_COLOR = "#5FAFFF"
_DIM_COLOR = "#8A8A8A"
_KEY_LABEL_STYLE = "dim"

_KEY_PRIORITY = {
    "TYPE": 0,
    "AGENT": 1,
    "MACHINE": 2,
    "PLAN": 3,
    "BUG": 4,
}


@dataclass(frozen=True)
class _TagChip:
    key: str
    marker: str
    marker_style: str | None
    key_style: str | None
    value: Text
    inline_gap: str


def inline_tag_text(tags: tuple[tuple[str, str], ...]) -> Text:
    text = Text()
    for index, chip in enumerate(_tag_chips(tags)):
        if index:
            text.append(" · ", style="dim")
        text.append_text(_inline_chip_text(chip))
    return text


def full_tag_lines(tags: tuple[tuple[str, str], ...]) -> tuple[Text, ...]:
    chips = _tag_chips(tags)
    if not chips:
        return ()

    key_width = max(len(_chip_label(chip)) for chip in chips)
    lines: list[Text] = []
    for chip in chips:
        label = _chip_label(chip)
        line = Text("     ")
        line.append(chip.marker or " ", style=chip.marker_style)
        line.append(" ")
        line.append(f"{label:<{key_width}}", style=chip.key_style)
        line.append("  ")
        line.append_text(chip.value)
        lines.append(line)
    return tuple(lines)


def _tag_chips(tags: tuple[tuple[str, str], ...]) -> tuple[_TagChip, ...]:
    ordered = sorted(
        enumerate(tags),
        key=lambda item: (
            _KEY_PRIORITY.get(item[1][0].upper(), len(_KEY_PRIORITY)),
            item[0],
        ),
    )
    return tuple(_tag_chip(key, value) for _idx, (key, value) in ordered)


def _inline_chip_text(chip: _TagChip) -> Text:
    text = Text()
    if chip.marker:
        text.append(chip.marker, style=chip.marker_style)
        text.append(chip.inline_gap)
    else:
        text.append(_chip_label(chip), style=chip.key_style)
        text.append(" ")
    text.append_text(chip.value)
    return text


def _chip_label(chip: _TagChip) -> str:
    return chip.key.lower()


def _tag_chip(key: str, value: str) -> _TagChip:
    canonical = key.upper()
    if canonical == "TYPE":
        color = _TYPE_COLORS.get(value.lower(), _TYPE_FALLBACK_COLOR)
        return _TagChip(
            key=canonical,
            marker="◆",
            marker_style=color,
            key_style=_KEY_LABEL_STYLE,
            value=Text(value, style=color),
            inline_gap=" ",
        )
    if canonical == "AGENT":
        return _TagChip(
            key=canonical,
            marker="@",
            marker_style=_AGENT_COLOR,
            key_style=_KEY_LABEL_STYLE,
            value=Text(value, style=_AGENT_COLOR),
            inline_gap="",
        )
    if canonical == "BUG":
        return _TagChip(
            key=canonical,
            marker="#",
            marker_style=_BUG_COLOR,
            key_style=_KEY_LABEL_STYLE,
            value=Text(value, style=_BUG_COLOR),
            inline_gap="",
        )
    if canonical == "PLAN":
        return _TagChip(
            key=canonical,
            marker="",
            marker_style=None,
            key_style=_KEY_LABEL_STYLE,
            value=_plan_value_text(value),
            inline_gap=" ",
        )
    if canonical == "MACHINE":
        return _TagChip(
            key=canonical,
            marker="",
            marker_style=None,
            key_style=_DIM_COLOR,
            value=Text(value, style=_DIM_COLOR),
            inline_gap=" ",
        )
    return _TagChip(
        key=canonical,
        marker="",
        marker_style=None,
        key_style=_KEY_LABEL_STYLE,
        value=Text(value),
        inline_gap=" ",
    )


def _plan_value_text(value: str) -> Text:
    text = Text()
    if "/" not in value:
        text.append(value, style=_PLAN_BASENAME_COLOR)
        return text

    directory, basename = value.rsplit("/", 1)
    text.append(f"{directory}/", style="dim")
    if basename:
        text.append(basename, style=_PLAN_BASENAME_COLOR)
    return text


__all__ = ["full_tag_lines", "inline_tag_text"]
