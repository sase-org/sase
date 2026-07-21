"""Read-only classification for pending agent handoffs."""

from pathlib import Path

PENDING_HANDOFF_MARKERS = (".sase_plan_pending", ".sase_questions_pending")


def has_pending_handoff(artifacts_dir: str | None) -> bool:
    """Return whether ``artifacts_dir`` contains a plan/question handoff."""
    if not artifacts_dir:
        return False

    try:
        return any(
            (Path(artifacts_dir) / marker).exists()
            for marker in PENDING_HANDOFF_MARKERS
        )
    except OSError:
        return False
