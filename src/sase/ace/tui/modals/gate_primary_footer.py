"""Shared presentation helpers for branch-driven gate footers."""

from __future__ import annotations

from rich.text import Text

from ..keymaps import key_display_name
from .gate_branch_controls import GateBranchData


_PRIMARY_ACTION_LABEL_MAX_CELLS = 32
_PRIMARY_ACTION_BADGE_STYLE = "bold #1a1a1a on #00D7AF"


def _primary_branch_label(data: GateBranchData) -> str:
    """Return the display label for the gate's declared primary branch."""
    options_by_id = {option.id: option for option in data.options}
    first_option_label = options_by_id[data.primary_branch[0]].label
    if len(data.primary_branch) == 1:
        return first_option_label

    primary_members = frozenset(data.primary_branch)
    group = next(
        (
            candidate
            for candidate in data.groups
            if frozenset(candidate.options) == primary_members
        ),
        None,
    )
    return group.label if group is not None and group.label else first_option_label


def primary_action_badge_for_label(label_text: str, submit_key: str) -> Text:
    """Build the bounded, literal key/action badge from a resolved label."""
    label = Text(label_text)
    label.truncate(_PRIMARY_ACTION_LABEL_MAX_CELLS, overflow="ellipsis")

    badge = Text(no_wrap=True)
    badge.append(
        f" {key_display_name(submit_key)}={label.plain} ",
        style=_PRIMARY_ACTION_BADGE_STYLE,
    )
    return badge


def primary_action_badge(data: GateBranchData, submit_key: str) -> Text:
    """Build the bounded, literal key/action badge for a gate footer."""
    return primary_action_badge_for_label(_primary_branch_label(data), submit_key)


__all__ = ["primary_action_badge", "primary_action_badge_for_label"]
