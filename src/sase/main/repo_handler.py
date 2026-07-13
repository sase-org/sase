"""Handler for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse
import json
import sys

from sase.repo_inventory import (
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    collect_repo_inventory,
)


def _print_human(inventory: RepoInventory) -> None:
    if not inventory.records:
        print("No repositories found.")
    else:
        print(f"{'NAME':<24} {'KIND':<8} {'PROJECT':<20} {'CLONED':<7} PATH")
        for record in inventory.records:
            print(
                f"{record.name:<24.24} "
                f"{record.kind:<8} "
                f"{record.project:<20.20} "
                f"{('yes' if record.exists else 'missing'):<7} "
                f"{record.path or '-'}"
            )

    for issue in inventory.issues:
        print(f"warning [{issue.project}]: {issue.message}", file=sys.stderr)


def _handle_list(args: argparse.Namespace) -> int:
    try:
        inventory = collect_repo_inventory(project=getattr(args, "project", None))
    except RepoInventoryProjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(inventory.to_json_dict(), indent=2, sort_keys=True))
    else:
        _print_human(inventory)
    return 0


_HANDLERS = {"list": _handle_list}


def handle_repo_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase repo ...`` command."""

    subcommand = getattr(args, "repo_subcommand", None)
    handler = _HANDLERS.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print("Usage: sase repo {list}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(handler(args))


__all__ = ["handle_repo_command"]
