"""Notification data model."""

from dataclasses import dataclass, field


@dataclass
class Notification:
    """A single notification entry."""

    id: str  # UUID4
    timestamp: str  # ISO-8601
    sender: str  # "crs", "fix-hook", etc.
    notes: list[str] = field(default_factory=list)  # Human-readable lines
    files: list[str] = field(default_factory=list)  # File paths
    action: str | None = None  # "HITL" | "JumpToChangeSpec" | "Tmux" | None
    action_data: dict[str, str] = field(default_factory=dict)
    read: bool = False
    dismissed: bool = False
