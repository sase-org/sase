"""In-memory, fold-aware clan dependency-wave ladder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from rich.cells import cell_len
from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ...models._agent_clan import clan_members
from ...models._agent_clan_waves import ClanWaveSummary, clan_wave_identity_key
from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from .._clan_wave_presentation import (
    WAVE_NUMBER_DONE_STYLE,
    WAVE_NUMBER_OPEN_STYLE,
    WAVE_UNRESOLVED_STYLE,
    append_clan_wave_state_pip,
    format_clan_wave_pips,
)
from ._agent_display_clan_sections_common import append_fold_heading
from ._member_in_flight import append_member_status_cell


class _WaveState(Protocol):
    @property
    def value(self) -> str: ...


class _Wave(Protocol):
    @property
    def number(self) -> int | None: ...

    @property
    def kind(self) -> str: ...

    @property
    def member_identities(self) -> tuple[str, ...]: ...

    @property
    def ghost_names(self) -> tuple[str, ...]: ...

    @property
    def state(self) -> _WaveState: ...

    @property
    def predecessor_identities(self) -> tuple[str, ...]: ...


class _MemberView(Protocol):
    @property
    def identity(self) -> str: ...

    @property
    def wave_index(self) -> int | None: ...

    @property
    def predecessors(self) -> tuple[str, ...]: ...

    @property
    def ghost_predecessors(self) -> tuple[str, ...]: ...

    @property
    def external_wait_count(self) -> int: ...


_DONE_STATES = frozenset({"done", "dismissed_only"})
_NOT_STARTED_STATES = frozenset({"not_started", "dismissed_only"})


def _wave_label(wave: _Wave) -> str:
    if wave.kind == "seal":
        return "∎"
    if wave.kind == "unresolved":
        return "?"
    return str(wave.number or "?")


def _wave_label_style(wave: _Wave) -> str:
    if wave.kind == "unresolved":
        return WAVE_UNRESOLVED_STYLE
    if wave.state.value in _DONE_STATES:
        return WAVE_NUMBER_DONE_STYLE
    return WAVE_NUMBER_OPEN_STYLE


def _heading_phrase(summary: ClanWaveSummary) -> str:
    """Describe the worst live state represented by the ladder."""
    waves = summary.waves
    failed = next((wave for wave in waves if wave.state.value == "failed"), None)
    if failed is not None:
        if failed.kind == "seal":
            return "land failed"
        if failed.kind == "unresolved":
            return "unresolved members failed"
        return f"wave {failed.number} failed"

    needs_you = next(
        (wave for wave in waves if wave.state.value == "needs_you"),
        None,
    )
    if needs_you is not None:
        if needs_you.kind == "seal":
            return "land needs you"
        if needs_you.kind == "unresolved":
            return "unresolved members need you"
        return f"wave {needs_you.number} needs you"

    in_flight = tuple(wave for wave in waves if wave.state.value == "in_flight")
    numbered_in_flight = tuple(wave for wave in in_flight if wave.kind == "number")
    if numbered_in_flight:
        numbers = tuple(str(wave.number) for wave in numbered_in_flight)
        if len(numbers) == 1:
            return f"wave {numbers[0]} in flight"
        if len(numbers) == 2:
            return f"waves {numbers[0]}, {numbers[1]} in flight"
        return f"{len(numbers)} waves in flight"
    if any(wave.kind == "seal" for wave in in_flight):
        return "land in flight"
    if in_flight:
        return "unresolved members in flight"

    if waves and all(wave.state.value in _DONE_STATES for wave in waves):
        return "all waves done"
    return "not started"


def _member_label(member: Agent, clan_name: str) -> str:
    name = member.presented_agent_name or member.step_name or member.display_name
    prefix = f"{clan_name}."
    return name[len(clan_name) :] if name.startswith(prefix) else name


def _heading_summary(summary: ClanWaveSummary) -> Text:
    result = Text()
    if summary.has_seal:
        result.append(f"{summary.numbered_wave_count} + land", style="dim")
    else:
        result.append(f"{summary.numbered_wave_count} waves", style="dim")
    result.append(" · ", style="dim")
    result.append_text(format_clan_wave_pips(summary))
    result.append(" · ", style="dim")
    result.append(_heading_phrase(summary), style="dim")
    return result


def _after_summary(
    wave: _Wave,
    member_views: Mapping[str, _MemberView],
    member_rows: Mapping[str, Agent],
    *,
    clan_name: str,
) -> str:
    if wave.kind == "seal":
        epic_land = any(
            (member := member_rows.get(identity)) is not None
            and member.epic_bead_id
            and not member.phase_bead_id
            for identity in wave.member_identities
        )
        result = "after every phase" if epic_land else "after every member"
    else:
        predecessors = tuple(
            identity
            for identity in wave.predecessor_identities
            if identity in member_views
        )
        labels = tuple(
            _member_label(member_rows[item], clan_name)
            for item in predecessors
            if item in member_rows
        )
        if len(labels) <= 3:
            result = f"after {' '.join(labels)}" if labels else "no dependencies"
        else:
            predecessor_wave_indices: set[int] = set()
            for identity in predecessors:
                wave_index = member_views[identity].wave_index
                if wave_index is not None:
                    predecessor_wave_indices.add(wave_index)
            predecessor_waves = sorted(predecessor_wave_indices)
            if len(predecessor_waves) == 1:
                result = f"after wave {predecessor_waves[0]}"
            elif predecessor_waves and predecessor_waves == list(
                range(predecessor_waves[0], predecessor_waves[-1] + 1)
            ):
                result = f"after waves {predecessor_waves[0]}–{predecessor_waves[-1]}"
            else:
                result = f"after {len(labels)} members"

    wave_members = tuple(
        member_views[identity]
        for identity in wave.member_identities
        if identity in member_views
    )
    dismissed_count = len(
        {ghost for member in wave_members for ghost in member.ghost_predecessors}
    )
    outside_count = sum(member.external_wait_count for member in wave_members)
    if dismissed_count:
        result += f" · {dismissed_count} dismissed"
    if outside_count:
        result += f" · +{outside_count} outside"
    return result


def _append_wave_row(
    text: Text,
    wave: _Wave,
    member_views: Mapping[str, _MemberView],
    member_rows: Mapping[str, Agent],
    *,
    clan_name: str,
) -> None:
    text.append("   ")
    text.append(_wave_label(wave), style=_wave_label_style(wave))
    text.append(" ")
    append_clan_wave_state_pip(text, wave.state.value)
    for identity in wave.member_identities:
        view = member_views.get(identity)
        member = member_rows.get(identity)
        if view is None or member is None:
            continue
        append_member_status_cell(
            text,
            _member_label(member, clan_name),
            bucket=agent_status_bucket(member),
        )


def _relative_ghost_label(name: str, clan_name: str) -> str:
    prefix = f"{clan_name}."
    return name[len(clan_name) :] if name.startswith(prefix) else name


def _append_member_wait_line(
    text: Text,
    member_view: _MemberView,
    member_views: Mapping[str, _MemberView],
    member_rows: Mapping[str, Agent],
    *,
    clan_name: str,
) -> None:
    if not (
        member_view.predecessors
        or member_view.ghost_predecessors
        or member_view.external_wait_count
    ):
        return

    member_row = member_rows.get(member_view.identity)
    if member_row is None:
        return
    text.append(f"     {_member_label(member_row, clan_name)}  waits on")
    has_wait = False
    for identity in member_view.predecessors:
        predecessor_view = member_views.get(identity)
        predecessor_row = member_rows.get(identity)
        if predecessor_view is None or predecessor_row is None:
            continue
        if has_wait:
            text.append(" ·")
        append_member_status_cell(
            text,
            _member_label(predecessor_row, clan_name),
            bucket=agent_status_bucket(predecessor_row),
        )
        has_wait = True
    for ghost in member_view.ghost_predecessors:
        if has_wait:
            text.append(" · ")
        else:
            text.append(" ")
        text.append(_relative_ghost_label(ghost, clan_name), style="dim #FFAF00")
        text.append(" ⊘", style="dim #FFAF00")
        has_wait = True
    if member_view.external_wait_count:
        if has_wait:
            text.append(" · ")
        else:
            text.append(" ")
        text.append(f"+{member_view.external_wait_count} outside", style="dim")
    text.append("\n")


def append_clan_waves_section(
    text: Text,
    agent: Agent,
    *,
    level: FoldLevel,
) -> None:
    """Append the live WAVES section from the clan's in-memory projection."""
    summary = agent.clan_waves
    if summary is None or not summary.layered:
        return

    append_fold_heading(
        text,
        title="WAVES",
        section_id="waves",
        level=level,
        count=None,
        summary=_heading_summary(summary),
    )
    if level == FoldLevel.COLLAPSED:
        return

    member_views = {member.identity: member for member in summary.members}
    member_rows = {
        clan_wave_identity_key(member): member for member in clan_members(agent)
    }
    clan_name = agent.presented_agent_name or agent.display_name
    rows: list[tuple[_Wave, Text, str]] = []
    for wave in summary.waves:
        line = Text()
        _append_wave_row(
            line,
            wave,
            member_views,
            member_rows,
            clan_name=clan_name,
        )
        rows.append(
            (
                wave,
                line,
                _after_summary(
                    wave,
                    member_views,
                    member_rows,
                    clan_name=clan_name,
                ),
            )
        )
    row_width = max((cell_len(line.plain) for _wave, line, _after in rows), default=0)
    for row_wave, line, after in rows:
        text.append_text(line)
        text.append(" " * (row_width - cell_len(line.plain) + 2))
        text.append(after, style="dim")
        text.append("\n")
        if level == FoldLevel.FULLY_EXPANDED:
            for identity in row_wave.member_identities:
                member_view = member_views.get(identity)
                if member_view is not None:
                    _append_member_wait_line(
                        text,
                        member_view,
                        member_views,
                        member_rows,
                        clan_name=clan_name,
                    )


__all__ = ["append_clan_waves_section"]
