"""Per-process Admin Center entry-selection bookmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProjectsSubTab = Literal["projects", "repos", "workspaces"]
UpdatesSubTab = Literal["core", "plugins", "agent-clis"]


@dataclass
class SelectionBookmark:
    """Requested selection plus the row a staged rebuild currently displays.

    ``identity``/``row`` hold the entry a caller has requested. When an
    asynchronous data source has not finished loading, a rebuild instead
    paints a stand-in row into ``displayed_identity``/``displayed_row`` and
    sets ``provisional`` so later callers know the paint does not satisfy the
    request.
    """

    identity: str | None = None
    row: int | None = None
    displayed_identity: str | None = None
    displayed_row: int | None = None
    provisional: bool = False

    def record(self, identity: str | None, row: int | None) -> None:
        """Store a user selection or an authoritative rebuild result."""
        self.identity = identity
        self.row = row
        self.displayed_identity = identity
        self.displayed_row = row
        self.provisional = False

    def display(self, identity: str | None, row: int | None) -> None:
        """Track a provisional row without replacing the requested selection."""
        self.displayed_identity = identity
        self.displayed_row = row
        self.provisional = True

    def rekey(self, old_identity: str, new_identity: str) -> None:
        """Replace a requested/displayed identity after its stable key is minted."""
        if self.identity == old_identity:
            self.identity = new_identity
        if self.displayed_identity == old_identity:
            self.displayed_identity = new_identity


@dataclass
class ProjectsSessionState:
    """Session-only cursor state for the Projects pane and sub-tabs."""

    active_subtab: ProjectsSubTab = "projects"
    projects: SelectionBookmark = field(default_factory=SelectionBookmark)
    repos: SelectionBookmark = field(default_factory=SelectionBookmark)
    workspaces: SelectionBookmark = field(default_factory=SelectionBookmark)
    repos_project_filter: str | None = None
    workspaces_project_filter: str | None = None


@dataclass
class TasksSessionState:
    """Session-only cursor state for the Tasks pane."""

    all_sessions: bool = False
    task: SelectionBookmark = field(default_factory=SelectionBookmark)


@dataclass
class UpdatesSessionState:
    """Session-only cursor state for the Updates pane and sub-tabs."""

    active_subtab: UpdatesSubTab = "core"
    plugins: SelectionBookmark = field(default_factory=SelectionBookmark)
    agent_clis: SelectionBookmark = field(default_factory=SelectionBookmark)


@dataclass
class AdminCenterSessionState:
    """Bounded Admin Center entry bookmarks for one ACE process."""

    config: SelectionBookmark = field(default_factory=SelectionBookmark)
    logs: SelectionBookmark = field(default_factory=SelectionBookmark)
    projects: ProjectsSessionState = field(default_factory=ProjectsSessionState)
    tasks: TasksSessionState = field(default_factory=TasksSessionState)
    updates: UpdatesSessionState = field(default_factory=UpdatesSessionState)
    xprompts: SelectionBookmark = field(default_factory=SelectionBookmark)


__all__ = [
    "AdminCenterSessionState",
    "ProjectsSessionState",
    "ProjectsSubTab",
    "SelectionBookmark",
    "TasksSessionState",
    "UpdatesSessionState",
    "UpdatesSubTab",
]
