"""Header rendering for tribe detail documents."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from ...agent_count_chip import format_agent_count_chip
from ...models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    TribeStatusCounts,
)
from ...models.fold_scale import TRIBE_FOLD_SCALE
from ...models.fold_state import FoldLevel
from ...models.tribe_display import tribe_config_key, tribe_identity_style
from ._agent_display_tribe_common import (
    BODY_STYLE,
    FIELD_LABEL_STYLE,
    STATUS_STYLES,
    TRIBE_IDENTITY_COLOR,
)
from ._fold_language import append_fold_header_line
from ._helpers import PROMPT_PANEL_LINE_CELL_LIMIT, wrap_text_by_cells

_TRIBE_HEADING_STYLE = f"bold {TRIBE_IDENTITY_COLOR} underline"
_DESCRIPTION_STYLE = "italic #C6C6C6"
_DESCRIPTION_MISSING_STYLE = "italic #8A8A8A"
_DESCRIPTION_CONFIG_KEY_STYLE = "bold #D7AF87"


def append_tribe_header(
    text: Text,
    snapshot: AgentTribeSummarySnapshot,
    fold_level: FoldLevel,
) -> None:
    text.append("TRIBE\n", style=_TRIBE_HEADING_STYLE)
    text.append("Name: ", style=FIELD_LABEL_STYLE)
    text.append(
        f"{snapshot.label}\n",
        style=tribe_identity_style(snapshot.panel_key, bold=True),
    )
    text.append("Status: ", style=FIELD_LABEL_STYLE)
    from sase.agent.status_buckets import status_bucket_for_values

    bucket = status_bucket_for_values(snapshot.status)
    text.append(snapshot.status, style=STATUS_STYLES.get(bucket, "bold"))
    _append_count_chip(text, snapshot.counts)
    text.append("\n")

    text.append("Composition: ", style=FIELD_LABEL_STYLE)
    composition: list[str] = []
    if snapshot.clan_count:
        composition.append(
            f"{snapshot.clan_count} clan{'s' if snapshot.clan_count != 1 else ''}"
        )
    if snapshot.family_count:
        composition.append(
            f"{snapshot.family_count} "
            f"famil{'ies' if snapshot.family_count != 1 else 'y'}"
        )
    composition.append(
        f"{snapshot.lane_count} lane{'s' if snapshot.lane_count != 1 else ''}"
    )
    if snapshot.nested_count:
        composition.append(f"{snapshot.nested_count} nested")
    text.append(" · ".join(composition) + "\n", style=BODY_STYLE)
    text.append("Runtime: ", style=FIELD_LABEL_STYLE)
    text.append(f"{snapshot.runtime_span}\n", style="bold #BCBCBC")
    append_fold_header_line(text, level=fold_level, scale=TRIBE_FOLD_SCALE)
    _append_description(text, snapshot)


def _append_count_chip(text: Text, counts: TribeStatusCounts) -> None:
    chip = format_agent_count_chip(
        stopped=counts.stopped,
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


def _append_description(text: Text, snapshot: AgentTribeSummarySnapshot) -> None:
    text.append("\n")
    if snapshot.description:
        for line in wrap_text_by_cells(
            snapshot.description, PROMPT_PANEL_LINE_CELL_LIMIT
        ):
            text.append(f"{line}\n", style=_DESCRIPTION_STYLE)
        return

    config_key = f"ace.tribes.{tribe_config_key(snapshot.panel_key)}.description"
    hint_prefix = "not set · add "
    if cell_len(hint_prefix) + cell_len(config_key) <= PROMPT_PANEL_LINE_CELL_LIMIT:
        text.append("not set", style=_DESCRIPTION_MISSING_STYLE)
        text.append(" · ", style="dim")
        text.append("add ", style=_DESCRIPTION_MISSING_STYLE)
        text.append(f"{config_key}\n", style=_DESCRIPTION_CONFIG_KEY_STYLE)
        return

    text.append("not set", style=_DESCRIPTION_MISSING_STYLE)
    text.append(" · ", style="dim")
    text.append("add\n", style=_DESCRIPTION_MISSING_STYLE)
    for line in wrap_text_by_cells(config_key, PROMPT_PANEL_LINE_CELL_LIMIT):
        text.append(f"{line}\n", style=_DESCRIPTION_CONFIG_KEY_STYLE)
