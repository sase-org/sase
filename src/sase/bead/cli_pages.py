"""Handlers for ``sase bead pages`` commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NoReturn


def handle_bead_pages(args: argparse.Namespace) -> NoReturn:
    """Run a generated bead-page operation."""

    action = getattr(args, "pages_action", None)
    if action is None:
        args._bead_pages_parser.print_help()
        sys.exit(0)
    if action == "refresh":
        _handle_refresh(args)
    if action == "url":
        _handle_url(args)
    print(f"Error: unknown bead pages subcommand: {action}", file=sys.stderr)
    sys.exit(2)


def _handle_refresh(args: argparse.Namespace) -> NoReturn:
    from sase.bead_pages.refresh import (
        bead_pages_refresh_to_json,
        refresh_bead_pages,
    )

    store, primary_root, project = _page_context(materialize=args.write)
    report = refresh_bead_pages(
        store,
        primary_root=primary_root,
        bead_id=args.bead,
        write=args.write,
        project=project,
    )
    if args.json:
        print(json.dumps(bead_pages_refresh_to_json(report), indent=2))
    else:
        _print_refresh(report)
    sys.exit(0 if report.ok else 1)


def _handle_url(args: argparse.Namespace) -> NoReturn:
    from sase.bead_pages.paths import bead_page_path
    from sase.sdd.hosted_links import hosted_link_resolver

    try:
        bead_page_path(args.bead_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    store, primary_root, project = _page_context(materialize=False)
    if not store.is_sidecar_storage or store.beads_dir is None:
        print(
            "No hosted bead page URL is available: "
            "this project has no recorded beads sidecar.",
            file=sys.stderr,
        )
        sys.exit(1)
    url = hosted_link_resolver(
        store,
        project=project,
        primary_root=primary_root,
    ).bead_url(args.bead_id)
    if url is None:
        print(
            f"No hosted bead page URL is available for {args.bead_id}: "
            "the beads sidecar has no resolvable hosted remote and branch.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(url)
    sys.exit(0)


def _print_refresh(report: Any) -> None:
    verb = "would change" if not report.write else "changed"
    mode = "dry run" if not report.write else "write"
    print(
        f"Bead page refresh {mode}: {len(report.actions)} pages {verb}; "
        f"{report.scanned} beads across {report.lineages} lineages scanned"
    )
    for action in report.actions:
        print(f"  {action.change}: {action.path}")
    if report.write and report.actions:
        status = "committed" if report.committed else "not committed"
        print(f"Beads-store batch: {status}")
    for issue in report.issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(
            f"{issue.severity}: {issue.path}: {issue.message} ({issue.code})",
            file=stream,
        )


def _page_context(*, materialize: bool) -> tuple[Any, Path, str | None]:
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import materialize_sdd_store, resolve_sdd_store

    primary_root, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
    store = (
        materialize_sdd_store(primary_root, workspace_num)
        if materialize
        else resolve_sdd_store(primary_root, workspace_num)
    )
    project = None
    try:
        from sase.workflows.utils import get_project_from_workspace

        project = get_project_from_workspace()
    except Exception:
        pass
    return store, primary_root, project


__all__ = ["handle_bead_pages"]
