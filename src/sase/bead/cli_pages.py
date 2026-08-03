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
    bead_id = _resolve_page_bead_id(store, args.bead)
    report = refresh_bead_pages(
        store,
        primary_root=primary_root,
        bead_id=bead_id,
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

    store, primary_root, project = _page_context(materialize=False)
    raw_bead_id = args.bead_id
    if raw_bead_id is None:
        print("Error: bead pages url requires a bead ID", file=sys.stderr)
        sys.exit(2)
    bead_id = _resolve_page_bead_id(store, raw_bead_id)
    assert bead_id is not None
    try:
        bead_page_path(bead_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
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
    ).bead_url(bead_id)
    if url is None:
        print(
            f"No hosted bead page URL is available for {bead_id}: "
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

    from sase.sdd.checkout_anchor import resolve_checkout_anchor

    anchor = resolve_checkout_anchor(Path.cwd())
    primary_root, workspace_num = workspace_context_for_plan_resolution(
        anchor.primary_root
    )
    store = (
        materialize_sdd_store(primary_root, workspace_num)
        if materialize
        else resolve_sdd_store(primary_root, workspace_num)
    )
    project = anchor.project_name
    if project is None:
        try:
            from sase.workflows.utils import get_project_from_workspace

            project = get_project_from_workspace()
        except Exception:
            pass
    return store, primary_root, project


def _resolve_page_bead_id(store: Any, bead_id: str | None) -> str | None:
    if bead_id is None or not store.is_sidecar_storage or store.beads_dir is None:
        return bead_id
    try:
        from sase.bead.store_locator import open_bead_project_for_beads_dir

        with open_bead_project_for_beads_dir(store.kind_root("beads")) as project:
            return project.resolve_id(bead_id)
    except KeyError:
        return bead_id
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


__all__ = ["handle_bead_pages"]
