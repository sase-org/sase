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
    "agent": ValueKind.AGENT,
    "bead_id": ValueKind.BEAD,
    "flag_key": ValueKind.FLAG,
    "memory_path": ValueKind.MEMORY,
    "model": ValueKind.MODEL,
    "monitor_id": ValueKind.MONITOR,
    "patch": ValueKind.PATCH,
    "plan": ValueKind.PLAN,
    "plan_file": ValueKind.PATH,
    "plugin": ValueKind.PLUGIN,
    "plugin_name": ValueKind.PLUGIN,
    "proc_id": ValueKind.PROC,
    "project": ValueKind.PROJECT,
    "repo": ValueKind.REPO,
    "skill": ValueKind.SKILL,
    "tag": ValueKind.TAG,
    "workflow_name": ValueKind.XPROMPT,
    "workspace": ValueKind.WORKSPACE,
    "workspace_num": ValueKind.WORKSPACE,
}

# Explicit (command_path, dest) overrides for actions whose dest/metavar is
# too ambiguous to resolve from NAME_TABLE alone. Bare names such as "id"
# and "name" are listed here one command path at a time.
_BEAD_ID_SLOTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("bead", "+1"), "id"),
    (("bead", "close"), "ids"),
    (("bead", "dep", "list"), "id"),
    (("bead", "dep", "tree"), "id"),
    (("bead", "epic-symbols"), "id"),
    (("bead", "history"), "id"),
    (("bead", "note"), "id"),
    (("bead", "open"), "id"),
    (("bead", "ref", "add"), "id"),
    (("bead", "ref", "list"), "id"),
    (("bead", "ref", "rm"), "id"),
    (("bead", "rm"), "ids"),
    (("bead", "show"), "id"),
    (("bead", "snooze"), "ids"),
    (("bead", "update"), "ids"),
)
_PATCH_NAME_COMMANDS: Final[tuple[str, ...]] = (
    "accept",
    "archive",
    "mail",
    "rebase",
    "restore",
    "revert",
    "rewind",
    "reword",
    "set-origin",
    "status",
    "submit",
    "sync",
    "tag",
)
_ARTIFACT_REF_SLOTS: Final[tuple[tuple[tuple[str, ...], str], ...]] = (
    (("artifact", "open"), "reference"),
    (("artifact", "path"), "reference"),
    (("artifact", "show"), "reference"),
    (("artifact", "trash", "restore"), "reference"),
    (("bead", "ref", "add"), "refs"),
    (("bead", "ref", "rm"), "refs"),
    (("patch", "ref", "add"), "refs"),
    (("patch", "ref", "rm"), "refs"),
)


def _build_path_overrides() -> dict[tuple[tuple[str, ...], str], ValueKind]:
    overrides: dict[tuple[tuple[str, ...], str], ValueKind] = {
        (("agent", "kill"), "name"): ValueKind.AGENT,
        (("agent", "revert"), "name"): ValueKind.AGENT,
        (("agent", "show"), "name"): ValueKind.AGENT,
        (("plan", "show"), "target"): ValueKind.PLAN,
        (("restore",), "name"): ValueKind.PATCH,
        (("revert",), "name"): ValueKind.PATCH,
        (("skill", "use"), "name"): ValueKind.SKILL,
        (("xprompt", "show"), "name"): ValueKind.XPROMPT,
    }
    for slot in _BEAD_ID_SLOTS:
        overrides[slot] = ValueKind.BEAD
    for command in _PATCH_NAME_COMMANDS:
        overrides[(("patch", command), "name")] = ValueKind.PATCH
    for slot in _ARTIFACT_REF_SLOTS:
        overrides[slot] = ValueKind.ARTIFACT
    return overrides


PATH_OVERRIDES: Final[dict[tuple[tuple[str, ...], str], ValueKind]] = (
    _build_path_overrides()
)


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
