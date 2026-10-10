"""Small presentation constants shared by auto-restart UX surfaces."""

from sase.agent.status_buckets import UPDATE_RECOVERY_GLYPH as UPDATE_RECOVERY_GLYPH

_FAILED_REPLACEMENT_OUTCOMES = frozenset(
    {
        "failed",
        "killed",
        "stopped",
        "epic_launch_failed",
        "timeout",
        "lost",
    }
)

__all__ = ["UPDATE_RECOVERY_GLYPH", "_FAILED_REPLACEMENT_OUTCOMES"]
