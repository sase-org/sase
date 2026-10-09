"""Before/after command snapshots for plugin lifecycle mutations.

Install, update, and uninstall capture the mounted-command set ahead of the
``uv`` mutation and again right after it, then diff the two snapshots so CLI
result panels and JSON payloads can announce added or removed commands and so
completion is refreshed only when the command set actually changed.

Snapshots use the disable-ignoring scan: lifecycle diffs must observe the real
on-disk command set even while a disable switch is active. Like
:mod:`sase.plugin_commands.scan`, this module imports only the standard
library plus the scan module — never plugin adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.plugin_commands.scan import scan_plugin_commands

#: Snapshot of the declared command set: command name -> entry details.
CommandSnapshot = dict[str, "CommandSnapshotEntry"]


@dataclass(frozen=True)
class CommandSnapshotEntry:
    """One declared command at snapshot time."""

    name: str
    distribution: str
    version: str
    location: str


@dataclass(frozen=True)
class CommandChange:
    """One command that appeared, disappeared, or changed provider details."""

    name: str
    distribution: str
    version: str

    def to_json(self) -> dict[str, str]:
        """Return the stable ``{name, distribution, version}`` JSON shape."""
        return {
            "name": self.name,
            "distribution": self.distribution,
            "version": self.version,
        }


@dataclass(frozen=True)
class CommandChanges:
    """Diff of two command snapshots."""

    added: tuple[CommandChange, ...] = ()
    removed: tuple[CommandChange, ...] = ()
    updated: tuple[CommandChange, ...] = ()

    def __bool__(self) -> bool:
        """Return whether any command was added, removed, or updated."""
        return bool(self.added or self.removed or self.updated)

    def to_json(self) -> dict[str, list[dict[str, str]]]:
        """Return the stable ``command_changes`` JSON shape."""
        return {
            "added": [change.to_json() for change in self.added],
            "removed": [change.to_json() for change in self.removed],
            "updated": [change.to_json() for change in self.updated],
        }


def take_command_snapshot() -> CommandSnapshot:
    """Capture the current declared command set, ignoring disable switches."""
    snapshot: CommandSnapshot = {}
    for record in scan_plugin_commands(honor_disable=False):
        snapshot[record.name] = CommandSnapshotEntry(
            name=record.name,
            distribution=record.distribution,
            version=record.version,
            location=record.location,
        )
    return snapshot


def diff_command_snapshots(
    before: CommandSnapshot, after: CommandSnapshot
) -> CommandChanges:
    """Diff two snapshots into added, removed, and updated command changes."""
    added = tuple(
        CommandChange(
            name=name,
            distribution=entry.distribution,
            version=entry.version,
        )
        for name, entry in sorted(after.items())
        if name not in before
    )
    removed = tuple(
        CommandChange(
            name=name,
            distribution=entry.distribution,
            version=entry.version,
        )
        for name, entry in sorted(before.items())
        if name not in after
    )
    updated = tuple(
        CommandChange(
            name=name,
            distribution=after[name].distribution,
            version=after[name].version,
        )
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    )
    return CommandChanges(added=added, removed=removed, updated=updated)


__all__ = [
    "CommandChange",
    "CommandChanges",
    "CommandSnapshot",
    "CommandSnapshotEntry",
    "diff_command_snapshots",
    "take_command_snapshot",
]
