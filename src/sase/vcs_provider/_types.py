"""Internal data types for VCS provider implementations."""

from dataclasses import dataclass
from typing import Literal

IssueState = Literal["open", "closed"]
IssueListState = Literal["open", "closed", "all"]
MergeVisibility = Literal["hide", "show", "only"]


@dataclass(frozen=True)
class IssueWire:
    """Provider-neutral representation of an external tracker issue.

    The record deliberately lives at the Python provider boundary rather than
    in :mod:`sase.core`: tracker commands and their JSON normalization are
    host/plugin concerns today.  Tuple-valued collections keep the frozen wire
    record immutable and safe to cache in the TUI.
    """

    number: int
    title: str
    state: IssueState
    body: str = ""
    labels: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    author: str = ""
    created_at: str = ""
    updated_at: str = ""
    url: str = ""
    comment_count: int = 0


@dataclass
class CommandOutput:
    """Result of running a VCS subprocess command.

    Used internally by provider implementations only, not exposed to consumers.
    """

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        """Whether the command succeeded (returncode == 0)."""
        return self.returncode == 0
