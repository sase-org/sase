"""Live-value kind classification for completable argparse slots."""

from __future__ import annotations

import argparse
from enum import StrEnum
from typing import Final


class ValueKind(StrEnum):
    """The live-value category a completable option or positional resolves to."""

    PROJECT = "project"
    BEAD = "bead"
    REPO = "repo"
    WORKSPACE = "workspace"
    PLUGIN = "plugin"
    FLAG = "flag"
    PLAN = "plan"
    PATCH = "patch"
    ARTIFACT = "artifact"
    XPROMPT = "xprompt"
    SKILL = "skill"
    MEMORY = "memory"
    PROC = "proc"
    MONITOR = "monitor"
    AGENT = "agent"
    MODEL = "model"
    TAG = "tag"
    PATH = "path"
    DIR = "dir"


_KIND_ATTR: Final = "_sase_completion_kind"

# Unambiguous dest/metavar strings that always resolve to the same kind,
# matched case-insensitively against an action's dest and, when set, its
# metavar. Bare, overloaded names such as "id" and "name" must never be added
# here -- resolve those one command path at a time through PATH_OVERRIDES
# instead, or a wrong kind will be offered somewhere it doesn't belong.
NAME_TABLE: Final[dict[str, ValueKind]] = {
    "project": ValueKind.PROJECT,
    "bead_id": ValueKind.BEAD,
    "repo": ValueKind.REPO,
    "workspace_num": ValueKind.WORKSPACE,
    "plugin": ValueKind.PLUGIN,
    "plugin_name": ValueKind.PLUGIN,
    "flag_key": ValueKind.FLAG,
    "monitor_id": ValueKind.MONITOR,
    "plan_file": ValueKind.PATH,
    "memory_path": ValueKind.MEMORY,
    "proc_id": ValueKind.PROC,
}

# Explicit (command_path, dest) overrides for actions whose dest/metavar is
# too ambiguous to resolve from NAME_TABLE alone. Extended one provider at a
# time as the "kinds" epic phase lands each value-kind's completion source.
PATH_OVERRIDES: Final[dict[tuple[tuple[str, ...], str], ValueKind]] = {
    (("bead", "show"), "id"): ValueKind.BEAD,
}


def set_completion_kind(action: argparse.Action, kind: ValueKind) -> None:
    """Record an explicit completion-kind override on *action*.

    Wins over both ``PATH_OVERRIDES`` and ``NAME_TABLE`` during resolution.
    """
    setattr(action, _KIND_ATTR, kind)


def resolve_value_kind(
    action: argparse.Action, command_path: tuple[str, ...]
) -> ValueKind | None:
    """Resolve the completion kind for *action* registered under *command_path*.

    Resolution order, first match wins: an explicit per-action override set by
    ``set_completion_kind``, a ``(command_path, dest)`` entry in
    ``PATH_OVERRIDES``, then a dest or metavar entry in ``NAME_TABLE``.
    """
    explicit = getattr(action, _KIND_ATTR, None)
    if explicit is not None:
        return explicit

    path_kind = PATH_OVERRIDES.get((command_path, action.dest))
    if path_kind is not None:
        return path_kind

    name_kind = NAME_TABLE.get(action.dest.lower())
    if name_kind is not None:
        return name_kind

    metavar = action.metavar
    if isinstance(metavar, str):
        return NAME_TABLE.get(metavar.lower())
    return None


__all__ = [
    "NAME_TABLE",
    "PATH_OVERRIDES",
    "ValueKind",
    "resolve_value_kind",
    "set_completion_kind",
]
