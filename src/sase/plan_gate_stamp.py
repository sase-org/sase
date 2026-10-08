"""Durable stamping of accepted Plan Decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase._plan_approval_protocol import PlanApprovalActionContext
from sase.notification_gates.models import GateError
from sase.plan_approval_actions import PlanApprovalActionError


def _ordered_stamped_decisions(
    raw_decisions: dict[str, Any],
    values: dict[str, Any],
    path_str: str,
    *,
    context: str,
) -> dict[str, Any]:
    """Build the stamped map in authored order, validating completeness."""
    authored_ids = [key for key, val in raw_decisions.items() if isinstance(val, dict)]
    for decision_id in values:
        if not isinstance(decision_id, str) or decision_id not in raw_decisions:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                path_str,
                f"decision {decision_id!r} is not in the authored {context}",
            )
        if not isinstance(raw_decisions.get(decision_id), dict):
            raise PlanApprovalActionError(
                "plan_archive_failed",
                path_str,
                f"decision {decision_id!r} is not in the authored {context}",
            )
    missing = [key for key in authored_ids if key not in values]
    if missing:
        raise PlanApprovalActionError(
            "plan_archive_failed",
            path_str,
            f"{context} is missing answers for: {', '.join(missing)}",
        )
    updated: dict[str, Any] = {}
    for decision_id, authored in raw_decisions.items():
        if not isinstance(authored, dict):
            continue
        value = values[decision_id]
        existing_answer = authored.get("answer")
        if existing_answer is not None and existing_answer != value:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                path_str,
                f"decision {decision_id!r} already stamped with a different answer",
            )
        entry = dict(authored)
        entry["answer"] = value
        updated[decision_id] = entry
    return updated


def _durable_answers_complete(raw_decisions: dict[str, Any]) -> bool:
    """Whether every authored decision already carries an answer."""
    for authored in raw_decisions.values():
        if isinstance(authored, dict) and authored.get("answer") is None:
            return False
    return True


def _stamp_is_complete_and_identical(
    raw_decisions: dict[str, Any],
    updated: dict[str, Any],
    values: dict[str, Any],
) -> bool:
    """Whether the durable file is already fully and identically stamped."""
    if not _durable_answers_complete(raw_decisions):
        return False
    for decision_id, value in values.items():
        if not isinstance(decision_id, str):
            continue
        if updated.get(decision_id, {}).get("answer") != value:
            return False
    return True


def stamp_durable_plan(
    notification: PlanApprovalActionContext,
    result: dict[str, Any],
    *,
    source: str,
    caller: str,
) -> None:
    """Write accepted decision answers into the durable plan file."""
    decisions = result.get("decisions")
    if not isinstance(decisions, dict) or not decisions:
        return
    decided_by, decided_via = _stamp_coordinates(source, caller)
    from sase._plan_approval_artifacts import durable_plan_file_for_context
    from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields

    durable = durable_plan_file_for_context(notification)
    if durable is None:
        raise PlanApprovalActionError(
            "plan_archive_failed", "durable_plan", "durable plan file is missing"
        )
    try:
        content = durable.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanApprovalActionError(
            "plan_archive_failed", str(durable), f"cannot read durable plan: {exc}"
        ) from exc
    frontmatter, _body, had = parse_frontmatter(content)
    if not had:
        raise PlanApprovalActionError(
            "plan_archive_failed", str(durable), "durable plan has no frontmatter"
        )
    raw_decisions = frontmatter.get("decisions")
    if not isinstance(raw_decisions, dict):
        raise PlanApprovalActionError(
            "plan_archive_failed", str(durable), "durable plan has no decisions map"
        )
    existing_by = frontmatter.get("decided_by")
    existing_via = frontmatter.get("decided_via")
    updated = _ordered_stamped_decisions(
        raw_decisions, decisions, str(durable), context="durable plan"
    )
    if existing_by is not None or existing_via is not None:
        if existing_by != decided_by:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(durable),
                "durable plan already stamped with a different decider",
            )
        if (existing_via or None) != decided_via:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(durable),
                "durable plan already stamped with a different surface",
            )
        if _stamp_is_complete_and_identical(raw_decisions, updated, decisions):
            return
        if _durable_answers_complete(raw_decisions):
            raise PlanApprovalActionError(
                "plan_archive_failed", str(durable), "durable plan answers differ"
            )
        # Compatible coordinates but missing answers: fall through and finish
        # the stamp below.
    fields: dict[str, Any] = {"decisions": updated, "decided_by": decided_by}
    if decided_via is not None:
        fields["decided_via"] = decided_via
    try:
        stamped = set_frontmatter_fields(content, fields)
        durable.write_text(stamped, encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanApprovalActionError(
            "plan_archive_failed", str(durable), f"cannot stamp durable plan: {exc}"
        ) from exc


def _stamp_coordinates(source: str, caller: str) -> tuple[str, str | None]:
    """Map gate source and caller to durable ``decided_by``/``decided_via``."""
    if source == "auto_resolution":
        return "auto", None
    if source in ("tui", "plan_response"):
        via = "tui"
    elif source == "cli":
        via = "cli"
    elif source == "mobile":
        via = "mobile"
    elif source == "telegram":
        via = "telegram"
    else:
        raise PlanApprovalActionError(
            "plan_archive_failed", source, f"unknown stamp source: {source}"
        )
    if caller == "human":
        by = "reviewer"
    elif caller == "agent":
        by = "agent"
    else:
        raise PlanApprovalActionError(
            "plan_archive_failed", caller, f"unknown stamp caller: {caller}"
        )
    return by, via


def stamp_direct_file(
    plan_path: Path,
    values: dict[str, Any],
    *,
    decided_by: str,
    decided_via: str | None,
) -> None:
    """Stamp resolved answers into a direct-approval plan file."""
    if not values:
        return
    from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields

    try:
        content = plan_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PlanApprovalActionError(
            "plan_archive_failed", str(plan_path), f"cannot read plan: {exc}"
        ) from exc
    frontmatter, _body, had = parse_frontmatter(content)
    if not had:
        raise PlanApprovalActionError(
            "plan_archive_failed", str(plan_path), "plan has no frontmatter"
        )
    raw_decisions = frontmatter.get("decisions")
    if not isinstance(raw_decisions, dict):
        return
    updated = _ordered_stamped_decisions(
        raw_decisions, values, str(plan_path), context="plan"
    )
    existing_by = frontmatter.get("decided_by")
    existing_via = frontmatter.get("decided_via")
    if existing_by is not None or existing_via is not None:
        if existing_by != decided_by:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(plan_path),
                "plan already stamped with a different decider",
            )
        if (existing_via or None) != decided_via:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(plan_path),
                "plan already stamped with a different surface",
            )
        if _stamp_is_complete_and_identical(raw_decisions, updated, values):
            return
        if _durable_answers_complete(raw_decisions):
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(plan_path),
                "plan already stamped with different answers",
            )
        # Compatible coordinates but missing answers: fall through and finish.
    fields: dict[str, Any] = {"decisions": updated, "decided_by": decided_by}
    if decided_via is not None:
        fields["decided_via"] = decided_via
    stamped = set_frontmatter_fields(content, fields)
    plan_path.write_text(stamped, encoding="utf-8")


__all__ = ["stamp_direct_file", "stamp_durable_plan"]
