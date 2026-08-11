"""Input and completion widgets used by the wait modal."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.agent_completion import status_style
from sase.ace.tui.models.tribe_display import (
    TRIBE_IDENTITY_FALLBACK_COLOR,
    compose_tribe_identity_style,
)

from .wait_modal_types import WaitAgentCandidate


class WaitInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class AgentCompletionList(OptionList):
    """Local completion list for waitable agents."""


class BeadCompletionList(OptionList):
    """Local completion list for waitable beads."""


def _truncate(value: str, width: int) -> str:
    """Truncate *value* to a fixed display width."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _status_style(status: str) -> str:
    return status_style(status)


def candidate_option(
    candidate: WaitAgentCandidate,
    index: int,
    *,
    tribe_colors: dict[str, str] | None = None,
) -> Option:
    """Render one agent completion row."""
    model = _truncate(candidate.model or "-", 18)
    start = candidate.start_time or "--:--"
    duration = _truncate(candidate.duration or "-", 8)
    role_parts = [part for part in (candidate.role, candidate.tribe) if part]
    role = _truncate("/".join(role_parts), 12) if role_parts else ""

    text = Text()
    text.append("● ", style=_status_style(candidate.status))
    text.append(f"{_truncate(candidate.label, 18):<18}", style="bold")
    text.append(" ")
    text.append(f"{_truncate(candidate.status, 10):<10}", style="dim")
    text.append(" ")
    text.append(f"{model:<18}", style="dim")
    text.append(" ")
    text.append(f"{start:<5}", style="dim")
    text.append(" ")
    text.append(f"{duration:<8}", style="dim")
    if role:
        text.append(" ")
        if candidate.tribe is None:
            text.append(role, style="dim")
        elif candidate.role is None:
            tribe_name = candidate.tribe.removeprefix("@")
            text.append(
                role,
                style=compose_tribe_identity_style(
                    (
                        tribe_colors.get(
                            tribe_name,
                            TRIBE_IDENTITY_FALLBACK_COLOR,
                        )
                        if tribe_colors is not None
                        else TRIBE_IDENTITY_FALLBACK_COLOR
                    ),
                    dim=True,
                ),
            )
        else:
            tribe_start = min(len(role), len(candidate.role) + 1)
            text.append(role[:tribe_start], style="dim")
            if tribe_start < len(role):
                tribe_name = candidate.tribe.removeprefix("@")
                text.append(
                    role[tribe_start:],
                    style=compose_tribe_identity_style(
                        (
                            tribe_colors.get(
                                tribe_name,
                                TRIBE_IDENTITY_FALLBACK_COLOR,
                            )
                            if tribe_colors is not None
                            else TRIBE_IDENTITY_FALLBACK_COLOR
                        ),
                        dim=True,
                    ),
                )
    return Option(text, id=f"wait-agent-{index}")
