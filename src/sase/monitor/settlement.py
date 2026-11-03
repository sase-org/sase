"""Public monitor claim, follow-up, and refresh settlement API."""

from __future__ import annotations

from sase.turns.settlement import (
    finalize_turn_workflow_state,
    project_name_from_artifacts_dir as shell_project_name_from_artifacts_dir,
    touch_turn_refresh_pulse,
)

from ._settlement_followup import LOST_FOLLOWUP_ERROR, settle_claim_and_followup


def touch_monitor_refresh_pulse(project_name: str | None) -> None:
    """Nudge artifact watchers after monitor metadata changes."""
    touch_turn_refresh_pulse(project_name)


def finalize_monitor_workflow_state(artifacts_dir: str) -> None:
    """Rewrite a settled monitor member's workflow_state.json to terminal."""
    finalize_turn_workflow_state(artifacts_dir)


def project_name_from_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the project containing a monitor artifacts directory."""
    return shell_project_name_from_artifacts_dir(artifacts_dir)


__all__ = [
    "LOST_FOLLOWUP_ERROR",
    "finalize_monitor_workflow_state",
    "project_name_from_artifacts_dir",
    "settle_claim_and_followup",
    "touch_monitor_refresh_pulse",
]
