"""Submitted plan-chain artifact classification."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    canonical_plan_chain_suffix,
)

from ._json_io import read_json_dict
from ._types import SubmittedPlanArtifact


def submitted_plan_artifact(
    *,
    meta: Mapping[str, Any],
    plan_path_marker: str | None,
    outcome: str | None,
) -> SubmittedPlanArtifact | None:
    """Classify a planner artifact as submitted-and-awaiting-review.

    Mirrors the meaning of the TUI ``PLAN`` status without importing TUI
    enrichment code: a ``--plan`` role row carrying a ``plan_submitted_at``
    marker that has not been superseded by approval, replan feedback, or a
    terminal ``done.json`` outcome, plus a usable plan path. Returns ``None``
    for anything else.
    """
    if outcome is not None:
        # A terminal outcome (approved/committed/rejected/killed) means the
        # plan flow has concluded; ordinary resolution applies instead.
        return None
    if canonical_plan_chain_suffix(meta.get("role_suffix")) != PLAN_CHAIN_PLAN_SUFFIX:
        return None
    if not _has_submission_marker(meta.get("plan_submitted_at")):
        return None
    if meta.get("plan_approved"):
        return None
    if _has_submission_marker(meta.get("feedback_submitted_at")):
        return None

    plan_path = first_nonempty_str(plan_path_marker, meta.get("plan_path"))
    if plan_path is None:
        return None

    name = meta.get("name")
    if not isinstance(name, str) or not name:
        return None
    base = agent_family_base(name) or name
    try:
        row_name = agent_family_phase_name(base, PLAN_CHAIN_PLAN_SUFFIX)
    except ValueError:
        return None
    return SubmittedPlanArtifact(
        plan_path=plan_path,
        planner_row_name=row_name,
        base_name=base,
    )


def submitted_plan_artifact_for_dir(
    artifact_dir: Path | str,
) -> SubmittedPlanArtifact | None:
    """Read an artifact dir and classify it as a submitted planner row."""
    artifact_path = Path(artifact_dir)
    meta = read_json_dict(artifact_path / "agent_meta.json")
    if meta is None:
        return None
    from ._artifact_state import done_outcome

    return submitted_plan_artifact(
        meta=meta,
        plan_path_marker=plan_path_marker(artifact_path),
        outcome=done_outcome(artifact_path),
    )


def plan_path_marker(artifact_dir: Path) -> str | None:
    data = read_json_dict(artifact_dir / "plan_path.json")
    if data is None:
        return None
    plan_path = data.get("plan_path")
    return plan_path if isinstance(plan_path, str) and plan_path else None


def _has_submission_marker(raw_value: object) -> bool:
    """Mirror the TUI's plan-submission marker check without importing it."""
    if isinstance(raw_value, str):
        return bool(raw_value)
    if isinstance(raw_value, list):
        return any(isinstance(value, str) and value for value in raw_value)
    return False


def first_nonempty_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None
