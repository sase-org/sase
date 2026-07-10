"""Shared types for the prompt history modal."""

from dataclasses import dataclass
from enum import Enum, auto

from sase.history.prompt import PromptEntry
from sase.history.prompt_metadata import PromptListSummary


class PromptHistoryAction(Enum):
    """Action type for prompt history modal result."""

    SUBMIT = auto()  # Enter - submit prompt directly
    EDIT_FIRST = auto()  # Ctrl+G - open in editor first
    LOAD = auto()  # Ctrl+I - load inline into the origin pane (other panes kept)


@dataclass
class PromptHistoryResult:
    """Result from PromptHistoryModal."""

    action: PromptHistoryAction
    prompt_text: str


@dataclass
class PromptDisplayItem:
    """Wrapper for prompt entry with display info."""

    entry: PromptEntry
    marker: str  # " " or "x"
    summary: PromptListSummary | None = None
    display_text: str | None = None
