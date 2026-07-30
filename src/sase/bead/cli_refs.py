"""Artifact-reference bead CLI handlers."""

from __future__ import annotations

import argparse
import json
import sys

from sase.artifact_ref_lists import (
    ArtifactRefListEntry,
    artifact_ref_list_display_lines,
    resolve_artifact_ref_list,
)
from sase.bead.cli_common import get_read_view
from sase.bead.cli_detail import artifact_reference_context
from sase.bead.model import Issue


def handle_bead_ref(args: argparse.Namespace) -> None:
    """Handle the Python slow path for resolved reference listings."""

    if args.ref_action != "list":
        raise RuntimeError(
            f"sase bead ref {args.ref_action} was not handled by the Rust fast path"
        )

    with get_read_view() as view:
        if args.id:
            try:
                issues = [view.show(args.id)]
            except KeyError:
                print(f"Error: issue not found: {args.id}", file=sys.stderr)
                raise SystemExit(1) from None
        else:
            issues = [issue for issue in view.list_issues() if issue.refs]

    if not args.resolve:
        _render_stored_references(issues, scoped=bool(args.id), as_json=args.json)
        return

    context = artifact_reference_context()
    resolved = [
        (
            issue,
            (
                resolve_artifact_ref_list(issue.refs, context=context)
                if context is not None
                else tuple(issue.refs)
            ),
        )
        for issue in issues
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "count": sum(len(entries) for _, entries in resolved),
                    "results": [
                        {
                            "issue_id": issue.id,
                            "refs": [
                                (
                                    entry.to_wire()
                                    if isinstance(entry, ArtifactRefListEntry)
                                    else {
                                        "rendered": entry,
                                        "resolution": None,
                                    }
                                )
                                for entry in entries
                            ],
                        }
                        for issue, entries in resolved
                    ],
                },
                indent=2,
            )
        )
        return

    lines: list[str] = []
    for issue, entries in resolved:
        display_lines = artifact_ref_list_display_lines(entries)
        if args.id:
            lines.extend(display_lines)
            continue
        for index, line in enumerate(display_lines):
            prefix = f"{issue.id}  " if index == 0 else " " * (len(issue.id) + 2)
            lines.append(f"{prefix}{line}")
    print("\n".join(lines) if lines else "No artifact references found.")


def _render_stored_references(
    issues: list[Issue],
    *,
    scoped: bool,
    as_json: bool,
) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "count": sum(len(issue.refs) for issue in issues),
                    "results": [
                        {"issue_id": issue.id, "refs": issue.refs} for issue in issues
                    ],
                },
                indent=2,
            )
        )
        return

    lines = [
        reference if scoped else f"{issue.id}  {reference}"
        for issue in issues
        for reference in issue.refs
    ]
    print("\n".join(lines) if lines else "No artifact references found.")


__all__ = ["handle_bead_ref"]
