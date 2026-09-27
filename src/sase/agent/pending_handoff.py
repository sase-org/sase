"""Read-only classification for pending agent handoffs."""

from pathlib import Path

PLAN_PENDING_MARKER = ".sase_plan_pending"
QUESTIONS_PENDING_MARKER = ".sase_questions_pending"
MONITOR_PENDING_MARKER = ".sase_monitor_pending"
GATE_PENDING_MARKER = ".sase_gate_pending"
PIPE_PENDING_MARKER = ".sase_pipe_pending"

PENDING_HANDOFF_MARKERS = (
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
    MONITOR_PENDING_MARKER,
    GATE_PENDING_MARKER,
    PIPE_PENDING_MARKER,
)

_MARKER_TO_KIND = {
    PLAN_PENDING_MARKER: "plan",
    QUESTIONS_PENDING_MARKER: "questions",
    MONITOR_PENDING_MARKER: "monitor",
    GATE_PENDING_MARKER: "gate",
    PIPE_PENDING_MARKER: "pipe",
}


def pending_handoff_kind(artifacts_dir: str | None) -> str | None:
    """Return the pending handoff kind, or ``None`` when there is none."""
    if not artifacts_dir:
        return None

    try:
        root = Path(artifacts_dir)
        for marker in PENDING_HANDOFF_MARKERS:
            try:
                if (root / marker).exists():
                    return _MARKER_TO_KIND[marker]
            except OSError:
                continue
    except (OSError, ValueError):
        return None
    return None


def has_pending_handoff(artifacts_dir: str | None) -> bool:
    """Return whether ``artifacts_dir`` contains a pending runner handoff."""
    return pending_handoff_kind(artifacts_dir) is not None
