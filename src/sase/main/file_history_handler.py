"""Handler for the 'sase file-history' command."""

import argparse
import json
import sys
from typing import Any


def handle_file_history_command(args: argparse.Namespace) -> None:
    """Handle the 'sase file-history' command."""
    subcommand = getattr(args, "file_history_subcommand", None)

    if subcommand == "list":
        _handle_list(args)
    elif subcommand == "delete":
        _handle_delete(args)
    else:
        print("Usage: sase file-history {list,delete}")
        sys.exit(1)


def _handle_list(args: argparse.Namespace) -> None:
    """Handle 'sase file-history list'."""
    from sase.history.file_references import load_file_references

    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.daemon.read_facade import read_or_fallback

    project_id = infer_project_name_from_cwd()
    if project_id is None:
        print(json.dumps(load_file_references()))
        sys.exit(0)

    result = read_or_fallback(
        "file_history",
        args=args,
        daemon_loader=lambda daemon: _daemon_file_history_paths(
            daemon, project_id=project_id
        ),
        direct_loader=load_file_references,
    )
    print(json.dumps(result.value))
    sys.exit(0)


def _daemon_file_history_paths(daemon: Any, *, project_id: str) -> list[str]:
    paths: list[str] = []
    cursor: str | None = None
    while True:
        raw = daemon.file_history(project_id=project_id, limit=500, cursor=cursor)
        rows = raw.get("file_history")
        if not isinstance(rows, list):
            from sase.daemon.client import LocalDaemonTransportError

            raise LocalDaemonTransportError(
                "file-history payload did not include file_history",
                code="projection_degraded",
                fallback_reason="unsupported_daemon_payload",
            )
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                paths.append(row["path"])
        page = raw.get("page")
        cursor = page.get("next_cursor") if isinstance(page, dict) else None
        if not isinstance(cursor, str) or not cursor:
            return paths


def _handle_delete(args: argparse.Namespace) -> None:
    """Handle 'sase file-history delete <path>'."""
    from sase.history.file_references import remove_file_reference

    remove_file_reference(args.path)
    sys.exit(0)
