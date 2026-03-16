"""In-memory activity event log for the ace TUI.

Records timestamped state transitions (idle ↔ active, session start/stop)
so the Activity Dashboard modal can display a rich timeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class ActivityEventType(Enum):
    """Types of activity state transition events."""

    SESSION_START = "session_start"
    ACTIVE = "active"
    IDLE_AUTO = "idle_auto"
    IDLE_MANUAL = "idle_manual"
    IDLE_PINNED = "idle_pinned"
    IDLE_RESTORED = "idle_restored"


@dataclass(frozen=True)
class _ActivityLogEntry:
    """A single activity state transition event."""

    timestamp: float  # wall-clock time.time()
    mono: float  # monotonic time for duration math
    event: ActivityEventType


@dataclass
class ActivityLog:
    """Append-only log of activity state transitions.

    Provides methods for recording events and computing summary
    statistics (total active/idle time, episode counts, etc.).
    """

    entries: list[_ActivityLogEntry] = field(default_factory=list)

    def record(self, event: ActivityEventType) -> None:
        """Append a new event with the current timestamp."""
        self.entries.append(
            _ActivityLogEntry(
                timestamp=time.time(),
                mono=time.monotonic(),
                event=event,
            )
        )

    @property
    def session_start_time(self) -> float | None:
        """Wall-clock time when the session started, or None."""
        for entry in self.entries:
            if entry.event == ActivityEventType.SESSION_START:
                return entry.timestamp
        return None

    @property
    def session_start_mono(self) -> float | None:
        """Monotonic time when the session started, or None."""
        for entry in self.entries:
            if entry.event == ActivityEventType.SESSION_START:
                return entry.mono
        return None

    def compute_totals(self) -> tuple[float, float, int]:
        """Compute total active time, total idle time, and idle episode count.

        Returns:
            (active_seconds, idle_seconds, idle_episodes)
        """
        if not self.entries:
            return 0.0, 0.0, 0

        now_mono = time.monotonic()
        active_total = 0.0
        idle_total = 0.0
        idle_episodes = 0

        for i, entry in enumerate(self.entries):
            # Duration of this state = time until next event (or now)
            if i + 1 < len(self.entries):
                duration = self.entries[i + 1].mono - entry.mono
            else:
                duration = now_mono - entry.mono

            if entry.event in (
                ActivityEventType.SESSION_START,
                ActivityEventType.ACTIVE,
            ):
                active_total += duration
            else:
                idle_total += duration
                idle_episodes += 1

        return active_total, idle_total, idle_episodes

    def current_state(self) -> _ActivityLogEntry | None:
        """Return the most recent event (current state)."""
        return self.entries[-1] if self.entries else None

    def is_idle(self) -> bool:
        """Whether the current state is any form of idle."""
        current = self.current_state()
        if current is None:
            return False
        return current.event in (
            ActivityEventType.IDLE_AUTO,
            ActivityEventType.IDLE_MANUAL,
            ActivityEventType.IDLE_PINNED,
            ActivityEventType.IDLE_RESTORED,
        )
