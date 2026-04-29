"""Handler for the ``sase changespec`` subcommands."""

from __future__ import annotations

import argparse
import os
import sys

from sase.ace.deltas import refresh_deltas_for_changespec
from sase.workflows.utils import get_project_file_path, get_project_from_workspace


def _resolve_project_file(explicit: str | None) -> str | None:
    """Resolve the project file path from --project-file or workspace inference."""
    if explicit:
        return os.path.expanduser(explicit)
    project = get_project_from_workspace()
    if not project:
        return None
    return get_project_file_path(project)


def _handle_sync_deltas(args: argparse.Namespace) -> int:
    project_file = _resolve_project_file(args.project_file)
    if not project_file:
        print(
            "[sase changespec sync-deltas] could not infer project file; "
            "pass -p/--project-file or run inside a sase workspace.",
            file=sys.stderr,
        )
        return 1
    if not os.path.isfile(project_file):
        print(
            f"[sase changespec sync-deltas] project file not found: {project_file}",
            file=sys.stderr,
        )
        return 1

    workspace_dir = args.workspace_dir or os.getcwd()
    ok = refresh_deltas_for_changespec(project_file, args.cl_name, workspace_dir)
    if ok:
        print(f"DELTAS refreshed for {args.cl_name} in {project_file}")
        return 0
    print(
        f"[sase changespec sync-deltas] failed to refresh DELTAS for {args.cl_name}; "
        "DELTAS preserved as-is. See logs for details.",
        file=sys.stderr,
    )
    return 1


def handle_changespec_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase changespec`` subcommands."""
    sub = getattr(args, "changespec_subcommand", None)
    if sub == "sync-deltas":
        sys.exit(_handle_sync_deltas(args))
    print(
        "Usage: sase changespec {sync-deltas} [-h]",
        file=sys.stderr,
    )
    sys.exit(1)
