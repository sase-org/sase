"""Bead attachment read commands: ``sase bead attachment list|open|path``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from sase.bead.attachment_presentation import (
    attachment_availability,
    attachment_descriptor,
    attachment_status_lines,
    attachment_view_path,
    strip_display_name,
)
from sase.bead.attachments.lifecycle import roster_for_issue
from sase.bead.cli_common import get_read_view, resolve_bead_operation_context
from sase.bead.model import BeadNoteAttachment, Issue, Status


def handle_bead_attachment(args: argparse.Namespace) -> None:
    """Dispatch one ``sase bead attachment`` action."""
    action = getattr(args, "attachment_action", None)
    if action in (None, "list", "open"):
        # List and open never fetch; they report the state the command sees.
        from sase.bead.attachments.fetch import fetch_context

        with fetch_context(mode="never"):
            _dispatch_bead_attachment(args, action)
    else:
        _dispatch_bead_attachment(args, action)


def _dispatch_bead_attachment(args: argparse.Namespace, action: str | None) -> None:
    """Run one ``sase bead attachment`` action inside its fetch context."""
    if action is None:
        _handle_bead_attachment_list(args)
    elif action == "path":
        _handle_bead_attachment_path(args)
    elif action == "open":
        _handle_bead_attachment_open(args)
    elif action == "list":
        _handle_bead_attachment_list(args)
    elif action == "push":
        _handle_bead_attachment_push(args)
    elif action == "purge":
        from sase.bead.cli_attachment_lifecycle import handle_bead_attachment_purge

        handle_bead_attachment_purge(args)
    elif action == "prune":
        from sase.bead.cli_attachment_lifecycle import handle_bead_attachment_prune

        handle_bead_attachment_prune(args)
    else:
        print(f"Unknown attachment action: {action}", file=sys.stderr)
        sys.exit(1)


def _handle_bead_attachment_list(args: argparse.Namespace) -> None:
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
    scoped = [issue for issue in issues if roster_for_issue(issue)]
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
    roster = roster_for_issue(issue)
    if as_json:
        print(_single_json(issue), end="")
        return
    if not roster:
        print(f"{issue.id}: no attachments.")
        return
    _print_roster_lines(issue)


def _print_roster_lines(issue: Issue) -> None:
    roster = roster_for_issue(issue)
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
        for status_line in attachment_status_lines(
            bead_id=issue.id,
            name=attachment.name,
            sha256=attachment.sha256,
            size_bytes=attachment.size_bytes,
            origin=getattr(attachment, "origin", None),
        ):
            print(f"    {status_line}")


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
    availability = attachment_availability(
        attachment.sha256,
        size_bytes=attachment.size_bytes,
        origin=getattr(attachment, "origin", None),
        name=attachment.name,
    )
    wire["availability"] = availability
    if availability == "cached":
        view = attachment_view_path(attachment.sha256, attachment.name)
        if view is not None:
            wire["local_path"] = view
    return wire


def _single_json(issue: Issue) -> str:
    roster = roster_for_issue(issue)
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
                    for attachment in roster_for_issue(issue).values()
                ],
            }
            for issue in issues
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _handle_bead_attachment_path(args: argparse.Namespace) -> None:
    """Print the absolute local view path for one attachment.

    Explicit path always fetches: the object downloads from the shared store
    even when it is above the auto-fetch cap.
    """
    from sase.bead.attachments.fetch import attachment_badge, fetch_context

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
    roster = roster_for_issue(issue)
    attachment = roster.get(name)
    if attachment is None:
        print(
            f"Error: attachment not found: {strip_display_name(name)} on {resolved_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    with fetch_context(mode="force"):
        state = attachment_availability(
            attachment.sha256,
            size_bytes=attachment.size_bytes,
            origin=getattr(attachment, "origin", None),
            name=attachment.name,
        )
        if state != "cached":
            badge = attachment_badge(
                state,
                size_bytes=attachment.size_bytes,
                bead_id=resolved_id,
                name=attachment.name,
                origin=getattr(attachment, "origin", None),
            )
            detail = f" ({badge})" if badge else ""
            print(
                f"Error: attachment {strip_display_name(name)} is not available"
                f"{detail} (no local object for sha256:{attachment.sha256[:12]}).",
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


def _handle_bead_attachment_open(args: argparse.Namespace) -> None:
    """Open one attachment in the terminal viewer, with n/p across viewables."""
    issue_id = args.id
    name = getattr(args, "name", None)
    bead_context = resolve_bead_operation_context([issue_id])
    resolved_id = bead_context.resolved_ids[0]
    with get_read_view(bead_context=bead_context) as view:
        try:
            issue = view.show(resolved_id)
        except KeyError:
            print(f"Error: issue not found: {issue_id}", file=sys.stderr)
            sys.exit(1)
    roster = roster_for_issue(issue)
    if not roster:
        print(f"Error: {resolved_id}: no attachments.", file=sys.stderr)
        sys.exit(1)
    if name is None:
        cached = sorted(
            attachment_name
            for attachment_name, record in roster.items()
            if attachment_availability(record.sha256) == "cached"
        )
        if not cached:
            print(
                f"Error: {resolved_id} has no cached attachments "
                "(✕ unavailable offline).",
                file=sys.stderr,
            )
            sys.exit(1)
        if len(cached) == 1:
            name = cached[0]
        else:
            import sys as _sys

            if _sys.stdin.isatty() and _sys.stderr.isatty():
                print(f"Attachments on {resolved_id}:", file=sys.stderr)
                for index, candidate in enumerate(cached, start=1):
                    print(f"  {index}. {candidate}", file=sys.stderr)
                try:
                    choice = input("Open which attachment [1]? ").strip() or "1"
                except (EOFError, KeyboardInterrupt):
                    print("Error: no attachment chosen.", file=sys.stderr)
                    sys.exit(1)
                try:
                    name = cached[int(choice) - 1]
                except (IndexError, ValueError):
                    print(
                        f"Error: invalid choice {choice!r}; "
                        f"choose 1-{len(cached)} or name one explicitly.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
            else:
                listing = ", ".join(cached)
                print(
                    f"Error: {resolved_id} has {len(cached)} cached attachments: "
                    f"{listing}; specify a name.",
                    file=sys.stderr,
                )
                sys.exit(2)
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
            "✕ unavailable offline on this machine.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from sase.bead.attachment_resolve import viewable_media_specs
    except Exception:
        viewable_media_specs = None  # type: ignore[assignment]
    specs: tuple[object, ...] = ()
    if viewable_media_specs is not None:
        try:
            specs = viewable_media_specs(issue, attachment.name)  # type: ignore[assignment]
        except Exception:
            specs = ()
    if not specs:
        view_path = attachment_view_path(attachment.sha256, attachment.name)
        if view_path is None:
            print(
                f"Error: attachment {strip_display_name(name)} is "
                "✕ unavailable offline on this machine.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            from sase.ace.tui.graphics import ArtifactFileViewSpec
        except Exception as exc:
            print(f"Error: viewer unavailable: {exc}", file=sys.stderr)
            sys.exit(1)
        specs = (ArtifactFileViewSpec(view_path, kind=None),)
    try:
        from sase.ace.tui.graphics import view_artifact_files
    except Exception as exc:
        print(f"Error: viewer unavailable: {exc}", file=sys.stderr)
        sys.exit(1)
    result = view_artifact_files(specs)  # type: ignore[arg-type]
    if getattr(result, "ok", True) is False:
        warnings = getattr(result, "warnings", ())
        detail = (
            "; ".join(str(getattr(item, "message", item)) for item in warnings)
            if warnings
            else "viewer failed"
        )
        print(f"Error: could not open {name}: {detail}", file=sys.stderr)
        sys.exit(1)


def _handle_bead_attachment_push(args: argparse.Namespace) -> None:
    """Drain the upload outbox and promote local-only objects.

    With an ID, drain only digests referenced by that bead; without one,
    drain the project outbox. Every configured tier drains (git, then the
    rclone large tier) with live TTY progress per object. Available with
    the flag off; it never authors notes.
    """
    from sase.bead.attachments.background import drain_project_outbox
    from sase.bead.attachments.upload import (
        discover_stores,
        promote_local_only,
        resolve_project_key,
    )

    scope_id = getattr(args, "id", None)
    bead_context = None
    only_digests: set[str] | None = None
    project_key: str | None = None
    if scope_id:
        bead_context = resolve_bead_operation_context([scope_id])
        resolved_id = bead_context.resolved_ids[0]
        with get_read_view(bead_context=bead_context) as view:
            try:
                issue = view.show(resolved_id)
            except KeyError:
                print(f"Error: issue not found: {scope_id}", file=sys.stderr)
                sys.exit(1)
        roster = roster_for_issue(issue)
        only_digests = {record.sha256 for record in roster.values()}
        project_key = resolve_project_key(bead_context)
    else:
        project_key = resolve_project_key(None)
    if project_key is None:
        print(
            "Error: cannot determine the project for attachment push.", file=sys.stderr
        )
        sys.exit(1)
    stores = discover_stores(bead_context)
    if not stores:
        print(
            "Error: no attachment shared store on this machine "
            "(neither attachments-private nor a large_store remote); "
            "attachments stay local.",
            file=sys.stderr,
        )
        sys.exit(1)
    drained, remaining = drain_project_outbox(
        project_key,
        time_bound_seconds=600.0,
        only_digests=only_digests,
        progress=True,
        stores=list(stores.values()),
    )
    promoted = promote_local_only(project_key, stores, time_bound_seconds=30.0)
    scope = f" for {scope_id}" if scope_id else ""
    print(
        f"Pushed {drained} attachment(s){scope}; "
        f"{remaining} queued; promoted {promoted} local-only."
    )


__all__ = [
    "handle_bead_attachment",
]
