"""Shared JSON serialization for the ``sase plugin`` CLI payloads.

Both ``sase plugin list`` and ``sase plugin show`` emit the same per-plugin
object shape under ``-j|--json``. This module is the single source of truth for
that shape so the two commands can never drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.plugins.catalog import PluginCatalogEntry
from sase.plugins.declared_commands import (
    DeclaredCommandProblem,
    DeclaredCommands,
    declared_commands_json,
    declared_problems,
)


def plugin_entry_json(
    entry: PluginCatalogEntry,
    *,
    declared_commands: DeclaredCommands | None = None,
    declared_problems_: Sequence[DeclaredCommandProblem] = (),
    command_owners: Mapping[str, str] | None = None,
    reserved_names: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Serialize one catalog entry to the stable ``-j|--json`` object shape.

    *declared_commands* is the upstream pre-install preview (phase sase-1if.6);
    when it reports ``declared`` names and no explicit *declared_problems_*
    are given, pre-consent collisions are computed (shared *command_owners* /
    *reserved_names* let ``list`` reuse one live scan across every entry).
    """
    current_version = entry.latest.current_version or entry.installed.version
    problems: Sequence[DeclaredCommandProblem] = declared_problems_
    if (
        declared_commands is not None
        and declared_commands.status == "declared"
        and not problems
    ):
        problems = declared_problems(
            declared_commands.names,
            command_owners=command_owners,
            reserved_names=reserved_names,
        )
    return {
        "name": entry.name,
        "repo": entry.repo,
        "full_name": entry.full_name,
        "owner": entry.owner,
        "kind": entry.kind,
        "description": entry.description,
        "url": entry.url,
        "homepage": entry.homepage,
        "topics": list(entry.topics),
        "stars": entry.stars,
        "archived": entry.archived,
        "license": entry.license,
        "updated_at": entry.updated_at,
        "install_type": entry.latest.install_type,
        "current_version": current_version,
        "installed": {
            "installed": entry.installed.installed,
            "version": entry.installed.version,
            "entry_point_groups": list(entry.installed.entry_point_groups),
            "commands": list(entry.installed.commands),
        },
        "latest": {
            "checked": entry.latest.checked,
            "version": entry.latest.version,
            "source": entry.latest.source,
            "update_available": entry.update_available,
            "state": entry.latest.state,
            "reason": entry.latest.reason,
            "error": entry.latest.error,
        },
        "declared_commands": declared_commands_json(declared_commands, problems),
    }


__all__ = ["plugin_entry_json"]
