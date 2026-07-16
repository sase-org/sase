"""Shared signal state and handlers for axe runners."""

import logging
import signal
import sys
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Global state for SIGTERM handler.
_killed_state: dict[str, object] = {"killed": False, "killed_at": None}


def was_killed() -> bool:
    """Check if the process received SIGTERM."""
    return bool(_killed_state["killed"])


def killed_at() -> float | None:
    """Return the wall-clock timestamp for the most recent SIGTERM."""
    value = _killed_state.get("killed_at")
    return value if isinstance(value, float) else None


def install_sigterm_handler(
    description: str = "process",
    *,
    soft: bool = False,
    on_signal: Callable[[], None] | None = None,
) -> None:
    """Install a SIGTERM handler that sets killed flag and exits gracefully.

    The handler uses sys.exit() instead of re-raising SIGTERM so that
    finally blocks run, ensuring workspace cleanup happens before exit.

    Args:
        description: What was killed (e.g., "agent", "mentor", "workflow").
        soft: When True, set the killed flag but don't call sys.exit().
            This allows the caller to detect the kill and handle it
            (e.g., check for marker files before deciding what to do).
        on_signal: Optional best-effort cleanup callback to run before exit.
    """

    def _handler(_signum: int, _frame: object) -> None:
        _killed_state["killed"] = True
        _killed_state["killed_at"] = time.time()
        print(f"\nReceived SIGTERM - {description} was killed", file=sys.stderr)
        if on_signal is not None:
            try:
                on_signal()
            except Exception:
                logger.exception("SIGTERM cleanup callback failed")
        if not soft:
            sys.exit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, _handler)


def reset_killed() -> None:
    """Clear the killed flag between follow-up loop iterations."""
    _killed_state["killed"] = False
    _killed_state["killed_at"] = None
