"""Validation for plugin-mounted top-level commands.

Classifies raw ``sase_commands`` records into mounted commands and problem
states (shadowed, conflict, invalid name). The reserved set is computed from
``_COMMAND_REGISTRARS`` plus the legacy root words plus ``help``, so built-ins
always win and later phases share one reservation rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sase.plugin_commands.scan import PluginCommandRecord, scan_plugin_commands

#: Command names must match this pattern to mount.
COMMAND_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

PluginCommandStatus = Literal["mounted", "shadowed", "conflict", "invalid_name"]


@dataclass(frozen=True)
class PluginCommandProblem:
    """One command name that cannot mount, with every owning distribution."""

    name: str
    status: Literal["shadowed", "conflict", "invalid_name"]
    distributions: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class PluginCommandSet:
    """Validated plugin commands with mounted and problem views."""

    records: tuple[PluginCommandRecord, ...]
    mounted: tuple[PluginCommandRecord, ...]
    problems: tuple[PluginCommandProblem, ...]

    def mounted_by_name(self) -> dict[str, PluginCommandRecord]:
        """Return mounted records keyed by command name."""
        return {record.name: record for record in self.mounted}

    def problem_by_name(self, name: str) -> PluginCommandProblem | None:
        """Return the problem for *name*, or ``None`` when it mounts cleanly."""
        for problem in self.problems:
            if problem.name == name:
                return problem
        return None


def validate_command_name(name: str) -> bool:
    """Return whether *name* is eligible to mount as a top-level command."""
    return COMMAND_NAME_RE.match(name) is not None


def reserved_command_names() -> frozenset[str]:
    """Return the command names plugins may never claim.

    Built-in registrars (including legacy aliases) always win, as do the
    legacy root words rewritten by ``normalize_legacy_root_args`` and the
    conventional ``help`` word.
    """
    from sase.legacy_xprompt_syntax import RETIRED_ROOT_COMMAND
    from sase.main.parser_registry import _COMMAND_REGISTRARS

    return frozenset(_COMMAND_REGISTRARS) | {"help", RETIRED_ROOT_COMMAND}


def discover_plugin_commands(*, honor_disable: bool = True) -> PluginCommandSet:
    """Classify ``sase_commands`` records into mounted commands and problems."""
    records = scan_plugin_commands(honor_disable=honor_disable)
    reserved = reserved_command_names()
    by_name: dict[str, list[PluginCommandRecord]] = {}
    for record in records:
        by_name.setdefault(record.name, []).append(record)

    mounted: list[PluginCommandRecord] = []
    problems: list[PluginCommandProblem] = []
    for name in sorted(by_name):
        owned = sorted(by_name[name], key=lambda record: record.distribution.casefold())
        distributions = tuple(record.distribution for record in owned)
        if not validate_command_name(name):
            problems.append(
                PluginCommandProblem(
                    name=name,
                    status="invalid_name",
                    distributions=distributions,
                    reason=f"'{name}' is not a valid command name (use lowercase letters, digits, and dashes, up to 32 characters); see sase doctor",
                )
            )
        elif name in reserved:
            problems.append(
                PluginCommandProblem(
                    name=name,
                    status="shadowed",
                    distributions=distributions,
                    reason=f"'{name}' is a built-in sase command name and cannot be provided by a plugin; see sase doctor",
                )
            )
        elif len(owned) > 1:
            problems.append(
                PluginCommandProblem(
                    name=name,
                    status="conflict",
                    distributions=distributions,
                    reason=f"'{name}' is claimed by more than one plugin ({', '.join(distributions)}); see sase doctor",
                )
            )
        else:
            mounted.append(owned[0])
    return PluginCommandSet(
        records=records, mounted=tuple(mounted), problems=tuple(problems)
    )
