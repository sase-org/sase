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
from sase.bead.note_codec import notes_to_dicts
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
    return (
        json.dumps(
            issue_detail_wire_dict(
                detail,
                created_by_url=created_by_url,
                page_url=page_url,
                include_links=include_links,
            ),
            indent=2,
        )
        + "\n"
    )


def issue_detail_wire_dict(
    detail: IssueDetail,
    *,
    created_by_url: str | None = None,
    page_url: str | None = None,
    include_links: bool | None = None,
) -> dict[str, object]:
    """Return the stable single-bead JSON envelope."""
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
    return envelope


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


def _enrich_note_dicts_with_availability(issue: Issue) -> list[dict[str, object]]:
    """Return ``notes_to_dicts`` plus ``availability``/``local_path`` per attachment.

    Only ``issue_to_wire_dict`` carries these keys; the store codec
    (``notes_to_dicts``) stays byte-identical. Beads without attachments do no
    attachment work and never import the store.
    """
    note_dicts = notes_to_dicts(issue.notes)
    if not any(note.attachments for note in issue.notes):
        return note_dicts  # type: ignore[return-value]
    from sase.bead.attachment_presentation import (
        attachment_availability,
        attachment_view_path,
    )
    from sase.bead.attachments.audience import read_audience_reason

    for note, note_dict in zip(issue.notes, note_dicts, strict=True):
        wire_list = note_dict.get("attachments")
        if not isinstance(wire_list, list):
            continue
        for wire in wire_list:
            if not isinstance(wire, dict):
                continue
            sha = wire.get("sha256")
            name = wire.get("name")
            if not isinstance(sha, str) or not isinstance(name, str):
                continue
            size = wire.get("size_bytes")
            origin = wire.get("origin")
            raw_visibility = wire.get("visibility")
            visibility = raw_visibility if isinstance(raw_visibility, str) else None
            wire["visibility"] = (
                visibility if visibility in ("public", "private") else "private"
            )
            reason = read_audience_reason(sha)
            if reason is not None:
                wire["audience_reason"] = reason
            availability = attachment_availability(
                sha,
                size_bytes=size if isinstance(size, int) else None,
                origin=origin if isinstance(origin, str) else None,
                name=name,
                visibility=visibility,
            )
            wire["availability"] = availability
            if availability == "cached":
                view = attachment_view_path(sha, name)
                if view is not None:
                    wire["local_path"] = view
    return note_dicts  # type: ignore[return-value]


def _evidence_attachment_dicts_with_availability(
    evidence: object,
) -> list[dict[str, object]] | None:
    """Return evidence attachments plus availability, or None when empty.

    Only ``issue_to_wire_dict`` carries ``availability``/``local_path``;
    the store codecs stay byte-identical. No bytes, no paths from the
    manifest itself, and no escape codes.
    """
    from sase.bead.attachment_presentation import (
        attachment_availability,
        attachment_view_path,
    )
    from sase.bead.attachments.audience import read_audience_reason
    from sase.bead.note_codec import attachment_to_dict

    attachments = getattr(evidence, "attachments", ())
    if not attachments:
        return None
    wire_list: list[dict[str, object]] = []
    for attachment in attachments:
        wire = dict(attachment_to_dict(attachment))
        entry: dict[str, object] = dict(wire)
        sha = wire.get("sha256")
        name = wire.get("name")
        raw_visibility = wire.get("visibility")
        visibility = raw_visibility if isinstance(raw_visibility, str) else None
        entry["visibility"] = (
            visibility if visibility in ("public", "private") else "private"
        )
        if isinstance(sha, str) and isinstance(name, str):
            size = wire.get("size_bytes")
            origin = wire.get("origin")
            reason = read_audience_reason(sha)
            if reason is not None:
                entry["audience_reason"] = reason
            availability = attachment_availability(
                sha,
                size_bytes=size if isinstance(size, int) else None,
                origin=origin if isinstance(origin, str) else None,
                name=name,
                visibility=visibility,
            )
            entry["availability"] = availability
            if availability == "cached":
                view = attachment_view_path(sha, name)
                if view is not None:
                    entry["local_path"] = view
        wire_list.append(entry)
    return wire_list


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
        **({"creation_reason": issue.creation_reason} if issue.creation_reason else {}),
        "notes": _enrich_note_dicts_with_availability(issue),
        "notes_text": issue.notes_text,
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
                **(
                    {
                        "attachments": _evidence_attachment_dicts_with_availability(
                            evidence
                        )
                    }
                    if getattr(evidence, "attachments", ())
                    else {}
                ),
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


__all__ = [
    "issue_detail_wire_dict",
    "issue_to_wire_dict",
    "ref_to_wire_dict",
    "render_issue_detail_json",
]
