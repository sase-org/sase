"""Code-swap guards for script-backed chops.

A ``sase dev update`` or ``just install*`` swap deletes and recreates console
scripts, Python modules, and the ``sase_core_rs`` extension while the
scheduler keeps ticking. These guards turn that fallout into an inhibited skip
that retries next tick instead of a loud failure:

* no job starts while a code-swap writer is live;
* a job script that is missing within :data:`CODE_SWAP_GRACE_SECONDS` of the
  last completed swap is still swap fallout;
* a run that overlapped a swap and died of SIGBUS or a swap-skew import error
  is a retry. Overlap decides, not the text alone: the same output with no
  swap on record stays a failure.

``sase.dev_update``'s package ``__init__`` pulls the update backend onto the
TUI first-paint path, so the lock and stamp modules are use-site imports. Every
probe here is best-effort and never raises: a probe that fails reads as "no
swap", which falls back to today's loud error.
"""

from __future__ import annotations

import signal
from collections.abc import Callable
from datetime import datetime

from sase.core.time import get_timezone

from .runner_failure_facts import capture_failure_facts

#: Returns a description of the live code-swap writer, or ``None``.
CodeSwapWriterProbe = Callable[[], str | None]

#: Exit status of a routine (lumberjack) that stopped because a code swap
#: completed under it. Its supervisor respawns it at once on the new code;
#: this is a clean restart, not a failure (``EX_TEMPFAIL``).
ROUTINE_SWAP_RESTART_EXIT_CODE = 75

_SIGBUS_EXIT = -int(signal.SIGBUS)


def code_swap_writer_holder() -> str | None:
    """Describe a live code-swap writer, or ``None`` (never raises)."""
    try:
        from sase.dev_update.code_swap_lock import (
            code_swap_writer_holder as probe,
        )

        return probe()
    except Exception:  # noqa: BLE001 - probe failure reads as no swap
        return None


def probe_writer(holder_fn: CodeSwapWriterProbe | None) -> str | None:
    """Run *holder_fn* (default: the real lock probe), swallowing failures."""
    try:
        return (holder_fn or code_swap_writer_holder)()
    except Exception:  # noqa: BLE001 - probe failure reads as no swap
        return None


def writer_live_reason(chop_name: str, holder: str) -> str:
    """Reason for a job that never started because a writer was live."""
    return (
        f"job {chop_name} did not start because a code swap is in progress "
        f"({holder}); retrying after the swap"
    )


def missing_script_writer_reason(script_name: str, holder: str) -> str:
    """Reason for a job script that vanished under a live writer."""
    return (
        f"job script {script_name} is unavailable while a code swap "
        f"is in progress ({holder}); retrying after the swap"
    )


def missing_script_grace_reason(
    script_name: str, *, now: datetime | None = None
) -> str | None:
    """Reason for a job script missing just after a swap, else ``None``.

    ``None`` means no swap completed within the grace window, so a missing
    script is the loud ``missing_script`` error.
    """
    try:
        from sase.dev_update.code_swap_stamp import (
            CODE_SWAP_GRACE_SECONDS,
            recent_code_swap,
        )

        current = now if now is not None else datetime.now(get_timezone())
        swap = recent_code_swap(now=current)
        if swap is None:
            return None
        age = max(0, int(swap.seconds_since_completed(current)))
        return (
            f"job script {script_name} is unavailable while a code swap settles "
            f"({swap.describe()}; {age}s ago, inside the "
            f"{int(CODE_SWAP_GRACE_SECONDS)}s post-swap grace); "
            "retrying after the swap"
        )
    except Exception:  # noqa: BLE001 - probe failure reads as no swap
        return None


def overlapping_exit_reason(
    *,
    chop_name: str,
    exit_code: int | None,
    output: str | None,
    started_at: datetime,
    finished_at: datetime,
    holder_fn: CodeSwapWriterProbe | None = None,
) -> str | None:
    """Reason to retry a failed run that overlapped a swap, else ``None``.

    The run qualifies only when both hold: it died of SIGBUS or its output
    matches the shared swap-skew patterns, and it overlapped a swap (a writer
    is live now, or the last recorded swap started before the run finished and
    completed after it started).
    """
    if exit_code is None or exit_code == 0:
        return None
    if exit_code == _SIGBUS_EXIT:
        symptom = f"died of SIGBUS (exit code {exit_code})"
    elif _output_looks_like_swap_skew(output):
        symptom = f"failed with a swap-skew import error (exit code {exit_code})"
    else:
        return None

    holder = probe_writer(holder_fn)
    swap_text = (
        f"still in progress: {holder}"
        if holder is not None
        else _last_swap_overlap_text(started_at, finished_at)
    )
    if swap_text is None:
        return None
    return (
        f"job {chop_name} {symptom} after overlapping a code swap "
        f"({swap_text}); retrying after the swap"
    )


def _output_looks_like_swap_skew(output: str | None) -> bool:
    if not output:
        return False
    facts = capture_failure_facts(None, phase="chop", error_text=output)
    return bool(facts.get("skew_suspect"))


def _last_swap_overlap_text(started_at: datetime, finished_at: datetime) -> str | None:
    try:
        from sase.dev_update.code_swap_stamp import read_last_code_swap

        swap = read_last_code_swap()
        if swap is None or not swap.overlaps(started_at, finished_at):
            return None
        return swap.describe()
    except Exception:  # noqa: BLE001 - probe failure reads as no swap
        return None


__all__ = [
    "ROUTINE_SWAP_RESTART_EXIT_CODE",
    "CodeSwapWriterProbe",
    "code_swap_writer_holder",
    "missing_script_grace_reason",
    "missing_script_writer_reason",
    "overlapping_exit_reason",
    "probe_writer",
    "writer_live_reason",
]
