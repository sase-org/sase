"""Clan identity fields for the sticky agent header panel."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.agent.status_buckets import QUEUED_STATUS, agent_status_bucket

from ...agent_count_chip import format_agent_count_chip
from ...models._agent_clan import ClanStatusCounts
from ...models.agent import Agent
from ...models.fold_scale import CLAN_FOLD_SCALE
from ...models.fold_state import FoldLevel
from ...models.tribe_display import (
    compose_tribe_identity_style,
    tribe_identity_colors,
)
from .._agent_list_render_agent_status import append_queued_status_extras
from .._agent_list_styling import _CLAN_NAME_STYLE
from ._agent_display_clan_roster import duration_label
from ._fold_language import append_fold_header_line
from ._identity_header_compact import (
    CHIP_SEPARATOR_STYLE,
    chips_row,
    compact_text,
    fold_chip,
)

CLAN_FIELD_LABEL_STYLE = "bold #87D7FF"
CLAN_MEMBER_STATUS_STYLES: dict[str, str] = {
    "Stopped": "bold #FFAF5F",
    "Starting": "bold #87D7FF",
    "Running": "bold #FFD700",
    "Queued": "bold #5F87FF",
    "Waiting": "bold #AF87FF",
    "Failed": "bold #FF5F5F",
    "Done": "bold #5FD75F",
}
_CLAN_TRIBE_CHIP_LIMIT = 3


def append_clan_identity_fields(
    text: Text,
    agent: Agent,
    *,
    counts: ClanStatusCounts,
    agent_count: int,
    family_count: int,
    fold_level: FoldLevel,
    now: datetime | None = None,
) -> None:
    """Append the clan identity block, minus the kind line."""
    text.append("Name: ", style=CLAN_FIELD_LABEL_STYLE)
    text.append(
        f"{agent.agent_clan or agent.display_name}\n",
        style=_CLAN_NAME_STYLE,
    )

    if agent.clan_tribes:
        tribe_colors = tribe_identity_colors(agent.clan_tribes)
        text.append("Tribes: ", style=CLAN_FIELD_LABEL_STYLE)
        for index, tribe in enumerate(agent.clan_tribes):
            if index:
                text.append(" ")
            text.append(
                f"@{tribe}",
                style=compose_tribe_identity_style(
                    tribe_colors[tribe],
                    bold=True,
                ),
            )
        text.append("\n")

    text.append("Status: ", style=CLAN_FIELD_LABEL_STYLE)
    status_bucket = agent_status_bucket(agent)
    text.append(agent.display_status, style=CLAN_MEMBER_STATUS_STYLES[status_bucket])
    if agent.status == QUEUED_STATUS:
        append_queued_status_extras(text, agent)
    chip = format_agent_count_chip(
        stopped=counts.awaiting,
        running=counts.running,
        queued=counts.queued,
        waiting=counts.waiting,
        failed=counts.failed,
        unread=counts.unread,
        done=counts.done,
    )
    if chip.cell_len:
        text.append(" ")
        text.append_text(chip)
    text.append("\n")

    text.append("Runtime: ", style=CLAN_FIELD_LABEL_STYLE)
    text.append(f"{duration_label(agent, now=now)}\n", style="bold #BCBCBC")

    text.append("Members: ", style=CLAN_FIELD_LABEL_STYLE)
    text.append(
        " · ".join(_member_summary_parts(agent_count, family_count)) + "\n",
        style="#D7D7FF",
    )

    append_fold_header_line(text, level=fold_level, scale=CLAN_FOLD_SCALE)


def build_clan_compact_lines(
    *,
    agent: Agent,
    counts: ClanStatusCounts,
    agent_count: int,
    family_count: int,
    fold_level: FoldLevel,
    now: datetime | None = None,
) -> Text:
    """Build the two-row compact identity for one clan document."""
    first = Text()
    first.append(
        f"{agent.agent_clan or agent.display_name}",
        style=_CLAN_NAME_STYLE,
    )
    first.append(" ", style="")
    status_bucket = agent_status_bucket(agent)
    first.append(
        agent.display_status,
        style=CLAN_MEMBER_STATUS_STYLES[status_bucket],
    )
    chip = format_agent_count_chip(
        stopped=counts.awaiting,
        running=counts.running,
        queued=counts.queued,
        waiting=counts.waiting,
        failed=counts.failed,
        unread=counts.unread,
        done=counts.done,
    )
    if chip.cell_len:
        first.append(" ", style="")
        first.append_text(chip)

    second = Text()
    tribes = tuple(agent.clan_tribes or ())
    if tribes:
        tribe_colors = tribe_identity_colors(tribes)
        for index, tribe in enumerate(tribes[:_CLAN_TRIBE_CHIP_LIMIT]):
            if index:
                second.append(" ", style="")
            second.append(
                f"@{tribe}",
                style=compose_tribe_identity_style(
                    tribe_colors[tribe],
                    bold=True,
                ),
            )
        overflow = len(tribes) - _CLAN_TRIBE_CHIP_LIMIT
        if overflow > 0:
            second.append(f" +{overflow}", style="dim")
        second.append(" · ", style=CHIP_SEPARATOR_STYLE)
    second.append(
        " · ".join(_member_summary_parts(agent_count, family_count)),
        style="",
    )
    second.append(" · ", style=CHIP_SEPARATOR_STYLE)
    second.append(f"{duration_label(agent, now=now)}", style="bold #BCBCBC")
    second.append(" · ", style=CHIP_SEPARATOR_STYLE)
    second.append_text(fold_chip(fold_level, CLAN_FOLD_SCALE))
    return compact_text(
        chips_row([first]),
        chips_row([second]),
    )


def _member_summary_parts(agent_count: int, family_count: int) -> list[str]:
    """Return the shared agent/family wording used by both identity forms."""
    parts = [f"{agent_count} agent{'s' if agent_count != 1 else ''}"]
    if family_count:
        parts.append(f"{family_count} famil{'ies' if family_count != 1 else 'y'}")
    return parts


__all__ = [
    "CLAN_FIELD_LABEL_STYLE",
    "CLAN_MEMBER_STATUS_STYLES",
    "append_clan_identity_fields",
    "build_clan_compact_lines",
]
