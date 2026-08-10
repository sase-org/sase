"""Internal data types for VCS provider implementations."""

from dataclasses import dataclass
from typing import Literal

IssueState = Literal["open", "closed"]
IssueListState = Literal["open", "closed", "all"]
PullRequestState = Literal["open", "closed"]
PullRequestListState = Literal["open", "closed", "all"]
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
    provider_id: str = ""


@dataclass(frozen=True)
class PullRequestWire:
    """Provider-neutral representation of an external pull request.

    Mirrors :class:`IssueWire`'s frozen, tuple-collection-only immutability
    contract at the same VCS provider boundary. ``state`` collapses to
    ``"open"``/``"closed"`` like :data:`IssueState`; ``merged_at`` is the
    signal that distinguishes a merged PR from a closed-unmerged one, since
    providers (e.g. GitHub) report those as distinct raw states.
    """

    number: int
    title: str
    state: PullRequestState
    provider_id: str = ""
    url: str = ""
    body: str = ""
    is_draft: bool = False
    author: str = ""
    head_ref: str = ""
    base_ref: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""
    merged_at: str = ""


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
