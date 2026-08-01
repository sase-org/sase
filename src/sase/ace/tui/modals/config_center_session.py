"""Per-process Admin Center entry-selection bookmarks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProjectsSubTab = Literal["projects", "repos", "workspaces"]
UpdatesSubTab = Literal["core", "plugins", "agent-clis"]


@dataclass
class SelectionBookmark:
    """Stable selected-entry identity plus its logical selectable row."""

    identity: str | None = None
    row: int | None = None

    def record(self, identity: str | None, row: int | None) -> None:
        """Store the resolved selection, or clear when no real row exists."""
        self.identity = identity
        self.row = row


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
