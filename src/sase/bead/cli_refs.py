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
    """Handle the Python slow path for reference mutations and listings."""

    action = args.ref_action or "list"
    if action in {"add", "rm"}:
        _handle_ref_mutation(action, args.id, list(args.refs))
        return
    if action != "list":
        print(f"Unknown ref action: {action}", file=sys.stderr)
        raise SystemExit(1)

    # A bare ``sase bead ref`` never reaches the list subparser, so the listing
    # options are absent from the namespace.
    scope = getattr(args, "id", None)
    as_json = bool(getattr(args, "json", False))

    with get_read_view() as view:
        if scope:
            try:
                issues = [view.show(scope)]
            except KeyError:
                print(f"Error: issue not found: {scope}", file=sys.stderr)
                raise SystemExit(1) from None
            except ValueError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        else:
            issues = [issue for issue in view.list_issues() if issue.refs]

    if not getattr(args, "resolve", False):
        _render_stored_references(issues, scoped=bool(scope), as_json=as_json)
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
    if as_json:
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
        if scope:
            lines.extend(display_lines)
            continue
        for index, line in enumerate(display_lines):
            prefix = f"{issue.id}  " if index == 0 else " " * (len(issue.id) + 2)
            lines.append(f"{prefix}{line}")
    print("\n".join(lines) if lines else "No artifact references found.")


def _handle_ref_mutation(action: str, issue_id: str, refs: list[str]) -> None:
    """Attach or detach references through the Rust bead CLI core.

    ``sase bead ref add``/``rm`` normally never reach argparse because the early
    Rust dispatch answers them first. That dispatch still declines whenever the
    bead store has not been materialized yet, so this deliberate fallback
    re-enters the same Rust core with a materialized store instead of failing.
    """
    from sase.main.bead_fast_path import execute_bead_cli

    exit_code = execute_bead_cli(["ref", action, issue_id, *refs], materialize=True)
    if exit_code is None:
        print(
            f"Error: sase bead ref {action} requires the sase Rust core; "
            "reinstall sase to restore it.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if exit_code != 0:
        raise SystemExit(exit_code)


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
