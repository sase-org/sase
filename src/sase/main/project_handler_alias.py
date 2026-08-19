"""Handlers for the ``sase project alias`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys

from sase.project_aliases import (
    ProjectAliasError,
    add_project_alias_locked as _add_project_alias_locked,
    clear_project_aliases_locked as _clear_project_aliases_locked,
    remove_project_alias_locked as _remove_project_alias_locked,
)

from .project_handler_lifecycle import (
    ProjectLifecycleError,
    get_project_record,
    list_aliased_project_records,
)
from .project_handler_render import (
    alias_json_payload,
    print_alias_records,
    print_alias_result,
)


def _handle_alias_list(args: argparse.Namespace) -> int:
    project = getattr(args, "project", None)
    try:
        if project:
            record = get_project_record(str(project))
            if args.json:
                print(json.dumps(alias_json_payload(record), indent=2, sort_keys=True))
            else:
                print_alias_result(record)
            return 0

        records = list_aliased_project_records()
    except (ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                [alias_json_payload(record) for record in records],
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_alias_records(records)
    return 0


def _handle_alias_add(args: argparse.Namespace) -> int:
    try:
        record = _add_project_alias_locked(str(args.project), str(args.alias))
    except (
        ValueError,
        ProjectAliasError,
        ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print_alias_result(record)
    return 0


def _handle_alias_remove(args: argparse.Namespace) -> int:
    try:
        record = _remove_project_alias_locked(str(args.project), str(args.alias))
    except (
        ValueError,
        ProjectAliasError,
        ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print_alias_result(record)
    return 0


def _handle_alias_clear(args: argparse.Namespace) -> int:
    try:
        record = _clear_project_aliases_locked(str(args.project))
    except (
        ValueError,
        ProjectAliasError,
        ProjectLifecycleError,
        ImportError,
        AttributeError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print_alias_result(record)
    return 0


_ALIAS_HANDLERS = {
    "list": _handle_alias_list,
    "add": _handle_alias_add,
    "remove": _handle_alias_remove,
    "clear": _handle_alias_clear,
}


def handle_alias(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``sase project alias ...`` command to its handler."""
    sub = getattr(args, "alias_subcommand", None)
    handler = _ALIAS_HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase project alias {add,clear,list,remove}",
            file=sys.stderr,
        )
        return 2
    return handler(args)
