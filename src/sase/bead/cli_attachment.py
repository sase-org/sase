"""Bead attachment read commands: ``sase bead attachment list|path``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from sase.bead.attachment_presentation import (
    attachment_availability,
    attachment_descriptor,
    attachment_view_path,
    strip_display_name,
)
from sase.bead.cli_common import get_read_view, resolve_bead_operation_context
from sase.bead.model import BeadNoteAttachment, Issue, Status


def handle_bead_attachment(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead attachment`` action."""
    action = getattr(args, "attachment_action", None)
    if action == "path":
        handle_bead_attachment_path(args)
    elif action == "list":
        handle_bead_attachment_list(args)
    else:
        print(f"Unknown attachment action: {action}", file=sys.stderr)
        sys.exit(1)


def _roster_for_issue(issue: Issue) -> dict[str, BeadNoteAttachment]:
    """Map attachment name to its latest model record for one issue."""
    roster: dict[str, BeadNoteAttachment] = {}
    for note in issue.notes:
        for attachment in note.attachments:
            roster[attachment.name] = attachment
    return roster


def handle_bead_attachment_list(args: argparse.Namespace) -> None:
    """List attachment descriptors for one bead, or every bead when unscoped."""
    issue_id = getattr(args, "id", None)
    as_json = bool(getattr(args, "json", False))
    if issue_id:
        bead_context = resolve_bead_operation_context([issue_id])
        resolved_id = bead_context.resolved_ids[0]
        with get_read_view(bead_context=bead_context) as view:
            try:
                issue = view.show(resolved_id)
            except KeyError:
                print(f"Error: issue not found: {issue_id}", file=sys.stderr)
                sys.exit(1)
        _print_single_list(issue, as_json=as_json)
        return
    with get_read_view() as view:
        issues = view.list_issues(
            statuses=[
                Status.OPEN,
                Status.CLAIMED,
                Status.READY,
                Status.SNOOZED,
                Status.IN_PROGRESS,
                Status.CLOSED,
            ],
        )
    scoped = [issue for issue in issues if _roster_for_issue(issue)]
    if as_json:
        print(_list_json(scoped), end="")
        return
    if not scoped:
        print("No bead attachments found.")
        return
    for issue in scoped:
        print(f"{issue.id} · {issue.title}")
        _print_roster_lines(issue)


def _print_single_list(issue: Issue, *, as_json: bool) -> None:
    roster = _roster_for_issue(issue)
    if as_json:
        print(_single_json(issue), end="")
        return
    if not roster:
        print(f"{issue.id}: no attachments.")
        return
    _print_roster_lines(issue)


def _print_roster_lines(issue: Issue) -> None:
    roster = _roster_for_issue(issue)
    for name in sorted(roster):
        attachment = roster[name]
        descriptor = attachment_descriptor(
            name=attachment.name,
            mime_type=attachment.mime_type,
            image=attachment.image,
            size_bytes=attachment.size_bytes,
            sha256=attachment.sha256,
        )
        print(f"  {descriptor}")
        if attachment_availability(attachment.sha256) == "cached":
            view = attachment_view_path(attachment.sha256, attachment.name)
            if view is not None:
                print(f"    {view}")
            else:
                print("    \u2715 unavailable offline")
        else:
            print("    \u2715 unavailable offline")


def _wire_with_availability(attachment: BeadNoteAttachment) -> dict[str, object]:
    wire: dict[str, object] = {
        "name": attachment.name,
        "sha256": attachment.sha256,
        "size_bytes": attachment.size_bytes,
        "mime_type": attachment.mime_type,
    }
    if attachment.image is not None:
        wire["image"] = {
            "width": attachment.image[0],
            "height": attachment.image[1],
        }
    if attachment.origin is not None:
        wire["origin"] = attachment.origin
    availability = attachment_availability(attachment.sha256)
    wire["availability"] = availability
    if availability == "cached":
        view = attachment_view_path(attachment.sha256, attachment.name)
        if view is not None:
            wire["local_path"] = view
    return wire


def _single_json(issue: Issue) -> str:
    roster = _roster_for_issue(issue)
    payload = {
        "id": issue.id,
        "attachments": [
            _wire_with_availability(roster[name]) for name in sorted(roster)
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _list_json(issues: Sequence[Issue]) -> str:
    payload = {
        "count": len(issues),
        "results": [
            {
                "id": issue.id,
                "title": issue.title,
                "attachments": [
                    _wire_with_availability(attachment)
                    for attachment in _roster_for_issue(issue).values()
                ],
            }
            for issue in issues
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def handle_bead_attachment_path(args: argparse.Namespace) -> None:
    """Print the absolute local view path for one attachment."""
    issue_id = args.id
    name = args.name
    bead_context = resolve_bead_operation_context([issue_id])
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        try:
            issue = view.show(resolved_id)
        except KeyError:
            print(f"Error: issue not found: {issue_id}", file=sys.stderr)
            sys.exit(1)
    roster = _roster_for_issue(issue)
    attachment = roster.get(name)
    if attachment is None:
        print(
            f"Error: attachment not found: {strip_display_name(name)} on {resolved_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    if attachment_availability(attachment.sha256) != "cached":
        print(
            f"Error: attachment {strip_display_name(name)} is "
            "\u2715 unavailable offline "
            "on this machine "
            f"(no local object for sha256:{attachment.sha256[:12]}).",
            file=sys.stderr,
        )
        sys.exit(1)
    view_path = attachment_view_path(attachment.sha256, attachment.name)
    if view_path is None:
        print(
            f"Error: attachment {strip_display_name(name)} is "
            "\u2715 unavailable offline on this machine.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(view_path)


__all__ = [
    "handle_bead_attachment",
    "handle_bead_attachment_list",
    "handle_bead_attachment_path",
]
