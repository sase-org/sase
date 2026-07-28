"""Responsive wait lanes for the agent detail header."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Table
from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    QUEUED_STATUS_COLOR,
)
from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference
from sase.core.wait_dependency_resolution import TribeWaitBinding

from ...agent_completion import missing_wait_dependency_names
from ...models.agent import Agent
from ...models.tribe_display import (
    compose_tribe_identity_style,
    named_tribe_identity_colors,
)
from .._agent_list_styling import (
    _MISSING_WAIT_TARGET_GLYPH,
    _MISSING_WAIT_TARGET_GLYPH_STYLE,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH,
    _UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
)

WAIT_SECTION_ID = "wait"
WAIT_FIELD_LABEL = "Wait: "
WAIT_FIELD_LABEL_STYLE = "bold #87D7FF"
_WAITING_VALUE_STYLE = "#FF87D7"
_WAIT_TAG_STYLES: dict[str, str] = {
    "agents": "dim #AF87FF",
    "tribes": "dim #FFD75F",
    "beads": "dim #FFAF00",
    "time": "dim #87D7FF",
    "runners": f"dim {QUEUED_STATUS_COLOR}",
}
# Glyphs mirror ``AGENT_STATUS_BUCKET_GLYPHS``; colors mirror agent-row status
# accents in ``_agent_list_render_agent.py`` / ``models.agent_status``.
_WAIT_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "Running": (AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "Queued": (
        AGENT_STATUS_BUCKET_GLYPHS["Queued"],
        f"bold {QUEUED_STATUS_COLOR}",
    ),
    "Waiting": (AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
    "Starting": (AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"),
    "Done": (AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "Failed": (AGENT_STATUS_BUCKET_GLYPHS["Failed"], "bold #FF5F5F"),
    "Stopped": (AGENT_STATUS_BUCKET_GLYPHS["Stopped"], "bold #8787AF"),
}
_WAIT_BEAD_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "closed": (AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "in_progress": (AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "claimed": (AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"),
    "open": (AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
}

type WaitLane = tuple[str, Text]


def _append_wait_status_badge(text: Text, bucket: str | None) -> None:
    """Append the standard badge for a known or unknown wait target."""
    badge = _WAIT_STATUS_BADGES.get(bucket) if bucket is not None else None
    if badge is None:
        glyph, style = (
            _MISSING_WAIT_TARGET_GLYPH,
            _MISSING_WAIT_TARGET_GLYPH_STYLE,
        )
    else:
        glyph, style = badge
    text.append(" ")
    text.append(glyph, style=style)


def _append_wait_bead_status_badge(text: Text, status: str | None) -> None:
    """Append the standard badge for a known or unknown bead status."""
    badge = _WAIT_BEAD_STATUS_BADGES.get(status) if status is not None else None
    if badge is None:
        glyph, style = (
            _MISSING_WAIT_TARGET_GLYPH,
            _MISSING_WAIT_TARGET_GLYPH_STYLE,
        )
    else:
        glyph, style = badge
    text.append(" ")
    text.append(glyph, style=style)


def _append_unresolvable_wait_marker(text: Text) -> None:
    text.append(" ")
    text.append(
        _UNRESOLVABLE_WAIT_TARGET_GLYPH,
        style=_UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE,
    )
    text.append(" (reserved - never resolves)", style="dim #FF5F5F")


def _append_clan_wait_members(
    value: Text,
    clan_members: Sequence[tuple[str, str]],
) -> None:
    """Append the established expanded clan-member wait detail."""
    done_count = sum(bucket == "Done" for _label, bucket in clan_members)
    value.append(" (", style="dim #AF87FF")
    value.append("all clan members", style="bold #AF87FF")
    value.append(
        f" · {done_count}/{len(clan_members)} done: ",
        style="dim #AF87FF",
    )
    for member_index, (label, bucket) in enumerate(clan_members):
        if member_index:
            value.append(" · ", style="dim #AF87FF")
        value.append(label, style=_WAITING_VALUE_STYLE)
        _append_wait_status_badge(value, bucket)
    value.append(")", style="dim #AF87FF")


def _tribe_target(reference: str) -> str | None:
    try:
        return parse_tribe_reference(reference)
    except InvalidTribeError:
        return None


def build_wait_lanes(
    agent: Agent,
    *,
    agent_status_buckets: Mapping[str, str] | None,
    clan_wait_member_statuses: Mapping[str, Sequence[tuple[str, str]]] | None,
    tribe_wait_bindings: Mapping[tuple[object, str], TribeWaitBinding] | None,
    wait_bead_statuses: Sequence[tuple[str, str | None]] | None,
    runner_queue_ahead_count: int | None,
) -> tuple[WaitLane, ...]:
    """Build ordered, styled values for each active wait dimension."""
    from sase.ace.tui.models.agent import (
        format_compact_duration,
        format_wait_until,
        wait_display_agent,
        wait_remaining_seconds,
    )

    wait_agent = wait_display_agent(agent)
    lanes: list[WaitLane] = []

    ordinary_targets = tuple(
        name for name in wait_agent.waiting_for if _tribe_target(name) is None
    )
    tribe_targets = tuple(
        (name, tribe)
        for name in wait_agent.waiting_for
        if (tribe := _tribe_target(name)) is not None
    )

    if ordinary_targets:
        value = Text()
        missing_names = missing_wait_dependency_names(agent, agent_status_buckets)
        missing_name_set = set(missing_names or ())
        for index, name in enumerate(ordinary_targets):
            if index:
                value.append(", ", style=_WAITING_VALUE_STYLE)
            value.append(name, style=_WAITING_VALUE_STYLE)
            clan_members = (
                clan_wait_member_statuses.get(name)
                if clan_wait_member_statuses is not None
                else None
            )
            if clan_members is not None:
                _append_clan_wait_members(value, clan_members)
            elif missing_names is not None:
                assert agent_status_buckets is not None
                target_bucket = (
                    None if name in missing_name_set else agent_status_buckets[name]
                )
                _append_wait_status_badge(value, target_bucket)
        lanes.append(("agents", value))

    if tribe_targets:
        value = Text()
        colors = named_tribe_identity_colors(
            {tribe for _reference, tribe in tribe_targets}
        )
        for index, (reference, tribe) in enumerate(tribe_targets):
            if index:
                value.append(", ", style=_WAITING_VALUE_STYLE)
            value.append(
                reference,
                style=compose_tribe_identity_style(colors[tribe], bold=True),
            )
            binding = (
                tribe_wait_bindings.get((wait_agent.identity, reference))
                if tribe_wait_bindings is not None
                else None
            )
            if binding is not None and binding.state == "reserved":
                _append_unresolvable_wait_marker(value)
                continue
            if binding is None or binding.name is None:
                value.append(" (next launch)", style="dim #AF87FF")
                continue
            value.append(" → ", style="dim #AF87FF")
            value.append(binding.name, style=_WAITING_VALUE_STYLE)
            target_bucket = (
                "Done"
                if binding.state == "bound"
                else (
                    agent_status_buckets.get(binding.name)
                    if agent_status_buckets is not None
                    else None
                )
            )
            if target_bucket is not None:
                _append_wait_status_badge(value, target_bucket)
            clan_members = (
                clan_wait_member_statuses.get(binding.name)
                if binding.kind == "clan" and clan_wait_member_statuses is not None
                else None
            )
            if clan_members is not None:
                _append_clan_wait_members(value, clan_members)
        lanes.append(("tribes", value))

    if wait_agent.waiting_for_beads:
        value = Text()
        if wait_bead_statuses is None:
            value.append(
                ", ".join(wait_agent.waiting_for_beads),
                style=_WAITING_VALUE_STYLE,
            )
        else:
            statuses_by_id = dict(wait_bead_statuses)
            for index, bead_id in enumerate(wait_agent.waiting_for_beads):
                if index:
                    value.append(", ", style=_WAITING_VALUE_STYLE)
                value.append(bead_id, style=_WAITING_VALUE_STYLE)
                _append_wait_bead_status_badge(
                    value,
                    statuses_by_id.get(bead_id),
                )
        lanes.append(("beads", value))

    time_part: str | None = None
    if wait_agent.wait_until:
        time_part = f"until {format_wait_until(wait_agent.wait_until)}"
    elif wait_agent.wait_duration:
        time_part = format_compact_duration(wait_agent.wait_duration)
    if time_part:
        value = Text(time_part, style=_WAITING_VALUE_STYLE)
        remaining = wait_remaining_seconds(agent)
        if remaining is not None and remaining > 0:
            value.append(
                f" ({format_compact_duration(remaining)} left)",
                style="dim #AF87FF",
            )
        lanes.append(("time", value))

    has_slot_wait = bool(
        wait_agent.slot_requested_at and wait_agent.wait_runners is not None
    )
    if has_slot_wait:
        value = Text()
        in_use = wait_agent.runner_slots_in_use
        threshold = wait_agent.wait_runners
        assert threshold is not None
        if wait_agent.wait_runners_explicit:
            value.append(f"≤ {threshold}", style=_WAITING_VALUE_STYLE)
            if threshold == 0:
                value.append(" (drain barrier)", style="bold #AF87FF")
            if in_use is not None:
                noun = "runner" if in_use == 1 else "runners"
                value.append(
                    f" · {in_use} {noun} still running",
                    style="dim #AF87FF",
                )
        elif in_use is not None:
            value.append(
                f"{in_use}/{threshold + 1} in use",
                style=_WAITING_VALUE_STYLE,
            )
        else:
            value.append(
                f"cap {threshold + 1}",
                style=_WAITING_VALUE_STYLE,
            )
        position = wait_agent.runner_slot_queue_position
        queue_size = wait_agent.runner_slot_queue_size
        if position is not None and queue_size is not None:
            value.append(
                f" · queue #{position} of {queue_size}",
                style="dim #AF87FF",
            )
        if wait_agent.wait_priority_explicit and wait_agent.wait_priority is not None:
            value.append(
                f" · priority {wait_agent.wait_priority}",
                style="dim #AF87FF",
            )
        lanes.append(("runners", value))

    return tuple(lanes)


def _wait_gutter_width(lanes: Sequence[WaitLane]) -> int:
    """Return the padded width of the widest present wait tag."""
    if not lanes:
        return 0
    return max(cell_len(f"[{tag}]") for tag, _value in lanes) + 1


@dataclass(slots=True)
class ResponsiveWaitSection:
    """Wait dimensions that wrap beneath one aligned value column."""

    lanes: tuple[WaitLane, ...]

    @property
    def logical_text(self) -> Text:
        """Return the styled, unwrapped wait block used for inspection."""
        gutter_width = _wait_gutter_width(self.lanes)
        text = Text(end="")
        for index, (tag, value) in enumerate(self.lanes):
            if index == 0:
                text.append(WAIT_FIELD_LABEL, style=WAIT_FIELD_LABEL_STYLE)
            else:
                text.append(" " * cell_len(WAIT_FIELD_LABEL))
            token = f"[{tag}]"
            text.append(token, style=_WAIT_TAG_STYLES[tag])
            text.append(" " * (gutter_width - cell_len(token)))
            text.append_text(value)
            text.append("\n")
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        gutter_width = _wait_gutter_width(self.lanes)
        for index, (tag, value) in enumerate(self.lanes):
            value.overflow = "fold"
            value.no_wrap = False
            table = Table.grid(padding=0)
            table.add_column(width=cell_len(WAIT_FIELD_LABEL), no_wrap=True)
            table.add_column(width=gutter_width, no_wrap=True)
            table.add_column(overflow="fold")
            label_text = (
                Text(WAIT_FIELD_LABEL, style=WAIT_FIELD_LABEL_STYLE)
                if index == 0
                else Text()
            )
            table.add_row(
                label_text,
                Text(f"[{tag}]", style=_WAIT_TAG_STYLES[tag]),
                value,
            )
            yield from console.render(table, options)


__all__ = [
    "WAIT_FIELD_LABEL",
    "WAIT_FIELD_LABEL_STYLE",
    "WAIT_SECTION_ID",
    "ResponsiveWaitSection",
    "WaitLane",
    "build_wait_lanes",
]
