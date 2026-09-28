"""Handler implementation for the ``sase goal`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.goals.cli import (
    handle_goal_doctor,
    handle_goal_drop,
    handle_goal_edit,
    handle_goal_list,
    handle_goal_merge,
    handle_goal_new,
    handle_goal_reopen,
    handle_goal_show,
)


def handle_goal_group(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase goal ...`` command."""
    subcommand = getattr(args, "goal_subcommand", None) or "list"
    if subcommand == "list":
        raise SystemExit(handle_goal_list(args))
    if subcommand == "show":
        raise SystemExit(handle_goal_show(args))
    if subcommand == "new":
        raise SystemExit(handle_goal_new(args))
    if subcommand == "edit":
        raise SystemExit(handle_goal_edit(args))
    if subcommand == "drop":
        raise SystemExit(handle_goal_drop(args))
    if subcommand == "reopen":
        raise SystemExit(handle_goal_reopen(args))
    if subcommand == "merge":
        raise SystemExit(handle_goal_merge(args))
    if subcommand == "doctor":
        raise SystemExit(handle_goal_doctor(args))
    raise SystemExit(2)


__all__ = ["handle_goal_group"]
