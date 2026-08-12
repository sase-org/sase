"""Runner-side history and logging helpers for declarative chop policy."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.core.time import get_timezone

from .chop_policy import (
    ChopCheckpointEvent,
    ChopPreflight,
    record_chop_checkpoint_event,
)
from .chop_runner_trace import NO_PYTHON_TRACEBACK
from .chop_runner_types import ChopRunOutcome
from .state import (
    ChopRunEntry,
    ChopRunSource,
    append_chop_run_output,
    write_chop_run,
)

# Trigger providers evaluate a configured condition and, on skip, mean "the
# condition was not met" — the chop should still wait out its next
# `run_every` interval before re-checking. Every other provider name is a
# guard, whose skip means "the trigger was never evaluated" and should not
# consume the cadence clock.
_TRIGGER_PROVIDERS = frozenset({"always", "git.commits_since"})


def append_once_per_summary(
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    decisions: dict[int, dict[str, str]],
) -> None:
    """Append proposal-level once-per decisions to a chop run log."""
    for index, decision in sorted(decisions.items()):
        outcome = decision.get("outcome", "unknown")
        key = decision.get("key") or "-"
        reason = decision.get("reason") or "-"
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Once-per proposal {index + 1}: {outcome} key={key} reason={reason}\n",
        )


def record_preflight_outcome(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    started_at: datetime,
    source: ChopRunSource,
    started_by: str | None,
    preflight: ChopPreflight,
    chop_verbose: bool,
) -> ChopRunOutcome:
    """Write and return a terminal skip or check-error preflight outcome."""
    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    status: Literal["skipped", "check_error"] = (
        "skipped" if preflight.outcome == "skip" else "check_error"
    )
    error = RuntimeError(preflight.reason) if status == "check_error" else None
    label = "Chop skipped" if status == "skipped" else "Chop preflight check error"
    output = f"{label}: {preflight.reason}\n"
    provider = (preflight.decision or {}).get("provider")
    advances_cadence = not (status == "skipped" and provider not in _TRIGGER_PROVIDERS)
    try:
        write_chop_run(
            ChopRunEntry(
                run_id=run_id,
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_ms=duration_ms,
                status=status,
                error=str(error) if error is not None else None,
                traceback=NO_PYTHON_TRACEBACK if error is not None else None,
                source=source,
                started_by=started_by,
                reason=preflight.reason,
            ),
            output=output,
        )
    except OSError:
        pass
    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop_name,
        status=status,
        run_id=run_id,
        error=error,
        traceback=NO_PYTHON_TRACEBACK if error is not None else None,
        chop_verbose=chop_verbose,
        reason=preflight.reason,
        advances_cadence=advances_cadence,
    )


def record_checkpoint_best_effort(
    lumberjack_name: str,
    chop_name: str,
    preflight: ChopPreflight,
    event: ChopCheckpointEvent,
    *,
    run_id: str | None = None,
) -> None:
    """Record a checkpoint event without obscuring the primary run outcome."""
    try:
        record_chop_checkpoint_event(lumberjack_name, chop_name, preflight, event)
    except Exception as exc:
        if run_id is not None:
            append_chop_run_output(
                lumberjack_name,
                chop_name,
                run_id,
                f"Checkpoint bookkeeping error: {exc}\n",
            )
