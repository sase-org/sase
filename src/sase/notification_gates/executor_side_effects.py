"""Post-response side-effect handling for notification-gate execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.notification_gates.failure_outcome import (
    SIDE_EFFECTS_ATTEMPT_ID,
    record_failure_outcome,
)
from sase.notification_gates.journal import append_journal_event
from sase.notification_gates.models import GateError

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin


def resume_side_effects(
    bundle_path: Path,
    *,
    adapter: Any,
    response: dict[str, Any],
    acceptance_id: str | None,
    epic_launch_origin: EpicLaunchOrigin | None,
    source: str,
) -> None:
    """Re-run only side effects for a resumed, already-answered gate.

    A post-response failure offers resume only. Adapters must skip a launch
    already recorded in ``response.json`` so the retry cannot launch a second
    successor.
    """
    request_hash = str(response.get("request_id") or "")
    append_journal_event(
        bundle_path,
        attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
        request_hash=request_hash,
        event="stage_started",
        stage="side_effects",
        acceptance_id=acceptance_id,
    )
    try:
        adapter.apply_side_effects(
            bundle_path=bundle_path,
            response=response,
            epic_launch_origin=epic_launch_origin,
        )
    except GateError as exc:
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
            stage="side_effects",
            error=exc,
            source=source,
            request_hash=request_hash,
        )
        raise
    except Exception as exc:
        wrapped = GateError(
            "side_effect_failed", adapter.kind, f"host side effect failed: {exc}"
        )
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
            stage="side_effects",
            error=wrapped,
            source=source,
            request_hash=request_hash,
        )
        raise wrapped from exc
    append_journal_event(
        bundle_path,
        attempt_id=SIDE_EFFECTS_ATTEMPT_ID,
        request_hash=request_hash,
        event="stage_completed",
        stage="side_effects",
        acceptance_id=acceptance_id,
    )
