"""Handler implementation for the ``sase project`` CLI subcommand."""

from __future__ import annotations

import argparse
import json
import sys

from sase.core.project_lifecycle_wire import (
    effective_project_name,
    is_disabled_project_lifecycle_state,
)
from sase.project_aliases import set_project_aliases_locked

from .project_handler_alias import handle_alias
from .project_handler_current import handle_current, handle_set_current
from .project_handler_lifecycle import (
    ProjectLifecycleBlockedError,
    ProjectLifecycleError,
    ProjectLifecycleNotFoundError,
    delete_project_locked,
    get_project_record,
    list_projects_for_state_filter,
    set_project_state_locked,
)
from .project_handler_render import (
    print_record_detail,
    print_records_table,
    record_to_json_dict,
)

__all__ = [
    "ProjectLifecycleBlockedError",
    "ProjectLifecycleError",
    "ProjectLifecycleNotFoundError",
    "delete_project_locked",
    "handle_project_command",
    "set_project_aliases_locked",
    "set_project_state_locked",
]


def _handle_list(args: argparse.Namespace) -> int:
    state_filter = str(args.state)
    try:
        records = list_projects_for_state_filter(state_filter)
    except (ValueError, ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                [record_to_json_dict(record) for record in records],
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print_records_table(records, state_filter)
    return 0


def _handle_show(args: argparse.Namespace) -> int:
    try:
        record = get_project_record(str(args.project))
    except (ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(record_to_json_dict(record), indent=2, sort_keys=True))
    else:
        print_record_detail(record)
    return 0


def _set_and_print(args: argparse.Namespace, state: str) -> int:
    try:
        record = set_project_state_locked(
            str(args.project),
            state,
            force=bool(args.force),
        )
    except (ProjectLifecycleError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    display = effective_project_name(record)
    print(f"Project '{display}' state is now {record.state}.")
    if is_disabled_project_lifecycle_state(record.state):
        print(f"Run 'sase project enable {display}' before launching new work.")
    return 0


def _handle_set_state(args: argparse.Namespace) -> int:
    return _set_and_print(args, str(args.state))


def _handle_enable(args: argparse.Namespace) -> int:
    return _set_and_print(args, "enabled")


def _handle_disable(args: argparse.Namespace) -> int:
    return _set_and_print(args, "disabled")


def _handle_activate(args: argparse.Namespace) -> int:
    return _handle_enable(args)


def _handle_deactivate(args: argparse.Namespace) -> int:
    return _handle_disable(args)


def _handle_archive(args: argparse.Namespace) -> int:
    return _handle_disable(args)


def _handle_close(args: argparse.Namespace) -> int:
    return _handle_disable(args)


_HANDLERS = {
    "activate": _handle_activate,
    "alias": handle_alias,
    "archive": _handle_archive,
    "close": _handle_close,
    "current": handle_current,
    "deactivate": _handle_deactivate,
    "disable": _handle_disable,
    "enable": _handle_enable,
    "list": _handle_list,
    "set-current": handle_set_current,
    "set-state": _handle_set_state,
    "show": _handle_show,
}


def handle_project_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase project ...`` command to its handler."""
    sub = getattr(args, "project_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase project "
            "{alias,current,disable,enable,list,set-current,set-state,show}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(handler(args))
