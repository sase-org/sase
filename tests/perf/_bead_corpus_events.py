"""Event payload construction and stream minting for the bead corpus."""

from __future__ import annotations

from typing import Any

from tests.perf._bead_corpus_common import (
    dump_payload,
    format_timestamp,
    mint_event_id,
)

__all__ = ["mint_stream_lines"]

_UPDATE_FIELD_ORDER = (
    "title",
    "status",
    "assignee",
    "description",
    "notes",
    "design",
    "model",
    "size",
    "closed_at",
    "close_reason",
    "changespec_name",
    "changespec_bug_id",
    "external_ref",
    "tier",
    "is_ready_to_work",
)


def _updated_fields(
    title: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build an ``issue_updated`` fields body in core's serialization order."""
    values = {"title": title, "description": description}
    return {name: values.get(name) for name in _UPDATE_FIELD_ORDER}


def _materialize_payload(
    operation: str,
    args: dict[str, Any],
    timestamp: str,
    actor: str,
    issue_id: str,
    note_ids: dict[tuple[str, int], str],
) -> dict[str, Any]:
    """Build an event payload in core's serialization order."""
    if operation == "issue_created":
        return {"kind": "issue_created", "issue": args["issue"]}
    if operation == "note_appended":
        return {"kind": "note_appended", "entry": args["entry"]}
    if operation == "issue_updated":
        return {
            "kind": "issue_updated",
            "fields": _updated_fields(
                title=args.get("title"), description=args.get("description")
            ),
        }
    if operation == "dependency_added":
        return {
            "kind": "dependency_added",
            "dependency": {
                "issue_id": issue_id,
                "depends_on_id": args["depends_on_id"],
                "created_at": timestamp,
                "created_by": actor,
            },
        }
    if operation == "reference_added":
        return {"kind": "reference_added", "reference": args["reference"]}
    if operation == "link_added":
        return {
            "kind": "link_added",
            "target_ref": args["target_ref"],
            "relation": args["relation"],
            "description": args["description"],
            "origin": "manual",
            "direction": "out",
            "uses": 1,
        }
    if operation == "task_plus_one_recorded":
        return {
            "kind": "task_plus_one_recorded",
            "evidence": {
                "timestamp": timestamp,
                "reporter": args["reporter"],
                "note": args["note"],
            },
        }
    if operation == "note_edited":
        return {
            "kind": "note_edited",
            "note_id": note_ids[(issue_id, args["note_no"])],
            "text": args["text"],
        }
    if operation == "note_removed":
        return {
            "kind": "note_removed",
            "note_id": note_ids[(issue_id, args["note_no"])],
        }
    if operation == "issue_closed":
        return {
            "kind": "issue_closed",
            "close_reason": None,
            "resolution": "done",
            "closed_by": actor,
        }
    if operation == "issue_removed":
        return {"kind": "issue_removed", "cascade_removed_issue_ids": []}
    raise ValueError(f"unknown synthetic operation: {operation}")


def mint_stream_lines(
    stream_id: str,
    items: list[tuple[Any, int, str, str, str, dict[str, Any]]],
    note_ids: dict[tuple[str, int], str],
) -> list[str]:
    """Sort one stream chronologically, mint every event ID, render lines."""
    ordered = sorted(items, key=lambda item: (item[0], item[1]))
    lines = []
    for ordinal, (when, _seq, issue_id, actor, operation, args) in enumerate(
        ordered, start=1
    ):
        timestamp = format_timestamp(when)
        payload = _materialize_payload(
            operation, args, timestamp, actor, issue_id, note_ids
        )
        event_id = mint_event_id(
            stream_id, ordinal, timestamp, actor, operation, issue_id, payload
        )
        if operation == "note_appended":
            note_ids[(issue_id, args["note_no"])] = event_id
        lines.append(
            dump_payload(
                {
                    "schema_version": 1,
                    "event_id": event_id,
                    "timestamp": timestamp,
                    "actor": actor,
                    "operation": operation,
                    "issue_id": issue_id,
                    "payload": payload,
                }
            )
        )
    return lines
