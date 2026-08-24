"""JSON serialization for bead detail commands."""

from __future__ import annotations

import json

import sase
from sase.bead.cli_detail_links import BeadLinkView
from sase.bead.cli_detail_resolution import IssueDetail, PlanLink
from sase.bead.close_history_codec import close_history_to_dicts
from sase.bead.flag_due import flag_removal_due
from sase.bead.flag_fields import flag_fields
from sase.bead.model import Dependency, Issue
from sase.bead.plus_one_presentation import evidence_recorded_after_current_close
from sase.bead.reopen_presentation import evidence_reopened_bead
from sase.bead.snooze_presentation import snooze_plus_ones_remaining
from sase.core import time as core_time


def render_issue_detail_json(
    detail: IssueDetail,
    *,
    created_by_url: str | None = None,
    page_url: str | None = None,
    include_links: bool | None = None,
) -> str:
    """Render a stable single-bead JSON envelope."""
    emit_links = detail.include_links if include_links is None else include_links
    issue_payload = issue_to_wire_dict(detail.issue)
    if not emit_links:
        issue_payload.pop("links", None)
    envelope: dict[str, object] = {
        "issue": issue_payload,
        "ancestors": [
            ref_to_wire_dict(ref.issue_id, ref.issue) for ref in detail.ancestors
        ],
        "children": {
            "phases": [
                ref_to_wire_dict(ref.issue_id, ref.issue) for ref in detail.phases
            ],
            "epics": [
                ref_to_wire_dict(ref.issue_id, ref.issue) for ref in detail.child_epics
            ],
        },
        "depends_on": [
            ref_to_wire_dict(ref.issue_id, ref.issue) for ref in detail.depends_on
        ],
        "blocks": [ref_to_wire_dict(ref.issue_id, ref.issue) for ref in detail.blocks],
        "plan": _plan_to_wire_dict(detail.plan),
    }
    if emit_links:
        envelope["artifact_links"] = [
            _artifact_link_to_wire_dict(view) for view in detail.artifact_links
        ]
    if created_by_url:
        envelope["created_by_url"] = created_by_url
    if page_url:
        envelope["page_url"] = page_url
    return json.dumps(envelope, indent=2) + "\n"


def _artifact_link_to_wire_dict(view: BeadLinkView) -> dict[str, object]:
    return {
        "source_ref": view.source_ref,
        "target_ref": view.target_ref,
        "relation": view.relation,
        "displayed_relation": view.displayed_relation,
        "direction": view.direction,
        "counterpart_ref": view.counterpart_ref,
        "reason": view.reason,
        "origin": view.origin,
        "actor": view.actor,
        "timestamp": view.timestamp,
        "uses": view.uses,
    }


def issue_to_wire_dict(issue: Issue) -> dict[str, object]:
    """Return the shared flat issue schema used by read-command JSON."""
    payload: dict[str, object] = {
        "id": issue.id,
        "title": issue.title,
        "status": issue.status.value,
        "issue_type": issue.issue_type.value,
        "tier": issue.tier.value if issue.tier else None,
        "size": issue.size.value if issue.size else None,
        "parent_id": issue.parent_id,
        "owner": issue.owner,
        "assignee": issue.assignee,
        "created_at": issue.created_at,
        "created_by": issue.created_by,
        "updated_at": issue.updated_at,
        "closed_at": issue.closed_at,
        "close_reason": issue.close_reason,
        "resolution": issue.resolution.value if issue.resolution else None,
        "close_history": close_history_to_dicts(issue.close_history),
        "snooze": _snooze_to_wire_dict(issue),
        "flag": _flag_to_wire_dict(issue),
        "description": issue.description,
        "notes": issue.notes_text,
        "design": issue.design,
        **({"refs": list(issue.refs)} if issue.refs else {}),
        "links": [
            {
                "target_ref": link.target_ref,
                "relation": link.relation,
                "description": link.description,
                "origin": link.origin,
            }
            for link in issue.links
        ],
        "plus_one_count": issue.plus_one_count,
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": list(evidence.refs),
                "observed_since": evidence.observed_since,
                # Derived here rather than left to the reader: agents use this
                # JSON to decide whether a duplicate is worth reviving, and
                # re-deriving the join is how renderings drift apart.
                "reopened_bead": evidence_reopened_bead(evidence, issue.close_history),
                "recorded_after_current_close": (
                    evidence_recorded_after_current_close(issue, evidence)
                ),
            }
            for evidence in issue.plus_one_evidence
        ],
        "model": issue.model,
        "is_ready_to_work": issue.is_ready_to_work,
        "changespec_name": issue.changespec_name,
        "changespec_bug_id": issue.changespec_bug_id,
        "external_ref": issue.external_ref,
        **({"task_type": issue.task_type} if issue.task_type else {}),
        **(
            {"task_type_fields": dict(issue.task_type_fields)}
            if issue.task_type_fields
            else {}
        ),
        "dependencies": [_dependency_to_wire_dict(dep) for dep in issue.dependencies],
    }
    return payload


def _snooze_to_wire_dict(issue: Issue) -> dict[str, object] | None:
    """Return the wake conditions, or ``None`` when the bead is not snoozed.

    ``plus_ones_remaining`` is derived here against the bead's live +1 count
    rather than left to the reader, for the same reason ``reopened_bead`` is:
    agents read this JSON to decide whether a snooze is nearly over, and
    re-deriving the subtraction is how renderings drift apart.
    """
    record = issue.snooze
    if record is None:
        return None
    return {
        "until": record.until,
        "snoozed_at": record.snoozed_at,
        "snoozed_by": record.snoozed_by,
        "plus_one_target": record.plus_one_target,
        "plus_one_baseline": record.plus_one_baseline,
        "reason": record.reason,
        "plus_ones_remaining": snooze_plus_ones_remaining(issue),
    }


def _flag_to_wire_dict(issue: Issue) -> dict[str, object] | None:
    """Return the removal thresholds and derived due state, or ``None``.

    ``due_state`` is derived here rather than left to the reader, for the
    same reason ``plus_ones_remaining`` is on the snooze record: agents read
    this JSON to decide whether a flag needs attention, and re-deriving the
    comparison is how renderings drift apart.
    """
    fields = flag_fields(issue)
    if fields is None:
        return None
    return {
        "key": fields.key,
        "remove_by_date": fields.remove_by_date,
        "remove_by_release": fields.remove_by_release,
        "due_state": flag_removal_due(
            fields.remove_by_date,
            fields.remove_by_release,
            today=core_time.local_now().date(),
            release=sase.__version__,
        ),
    }


def _dependency_to_wire_dict(dep: Dependency) -> dict[str, str]:
    return {
        "issue_id": dep.issue_id,
        "depends_on_id": dep.depends_on_id,
        "created_at": dep.created_at,
        "created_by": dep.created_by,
    }


def ref_to_wire_dict(issue_id: str, issue: Issue | None) -> dict[str, object]:
    """Return the shared resolved-or-dangling bead reference schema."""
    return {
        "id": issue_id,
        "resolved": issue is not None,
        "title": issue.title if issue else None,
        "status": issue.status.value if issue else None,
        "issue_type": issue.issue_type.value if issue else None,
        "tier": issue.tier.value if issue and issue.tier else None,
        "size": issue.size.value if issue and issue.size else None,
    }


def _plan_to_wire_dict(plan: PlanLink | None) -> dict[str, object] | None:
    if plan is None:
        return None
    return {
        "section": plan.section,
        "source": plan.source,
        "path": plan.path,
        "from": (
            ref_to_wire_dict(plan.from_ref.issue_id, plan.from_ref.issue)
            if plan.from_ref
            else None
        ),
    }


__all__ = ["issue_to_wire_dict", "ref_to_wire_dict", "render_issue_detail_json"]
