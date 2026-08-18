"""Read-only classification for pending agent handoffs."""

from pathlib import Path

PLAN_PENDING_MARKER = ".sase_plan_pending"
QUESTIONS_PENDING_MARKER = ".sase_questions_pending"
MONITOR_PENDING_MARKER = ".sase_monitor_pending"
PIPE_PENDING_MARKER = ".sase_pipe_pending"

PENDING_HANDOFF_MARKERS = (
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
    MONITOR_PENDING_MARKER,
    PIPE_PENDING_MARKER,
)


def has_pending_handoff(artifacts_dir: str | None) -> bool:
    """Return whether ``artifacts_dir`` contains a pending runner handoff."""
    if not artifacts_dir:
        return False

    try:
        return any(
            (Path(artifacts_dir) / marker).exists()
            for marker in PENDING_HANDOFF_MARKERS
        )
    except OSError:
        return False
