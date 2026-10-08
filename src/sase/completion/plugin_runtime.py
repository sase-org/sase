"""Runtime completion spec: the builtin tree plus mounted plugin subtrees.

:func:`build_spec` stays builtin-only so the checked-in structural snapshot,
kind coverage, and run-policy contracts remain hermetic. This module merges
one root child per mounted plugin command for every live consumer: ``sase
completion spec``, the bash/zsh/fish emitters, the runtime grammar cache,
and the TUI command-line spec subprocess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any

from sase.completion.build import build_plugin_command, build_spec
from sase.completion.model import CompletionSpec

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PluginCommandOmission:
    """One mounted command left out of the runtime spec, with its cause."""

    name: str
    distribution: str
    version: str
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "distribution": self.distribution,
            "version": self.version,
            "reason": self.reason,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PluginCommandOmission:
        return cls(
            name=str(data["name"]),
            distribution=str(data["distribution"]),
            version=str(data["version"]),
            reason=str(data["reason"]),
        )


@dataclass(frozen=True, slots=True)
class _RuntimeCompletionSpec:
    """The merged runtime spec plus every omitted plugin subtree."""

    spec: CompletionSpec
    omissions: tuple[PluginCommandOmission, ...] = field(default_factory=tuple)

    def structural_view(self) -> dict[str, Any]:
        """Return the structural view of the merged runtime spec."""
        return self.spec.structural_view()


def build_runtime_spec() -> _RuntimeCompletionSpec:
    """Return the builtin spec plus one root child per mounted command.

    Each child comes from its adapter's ``build_parser(prog=f"sase {name}")``
    walked in plugin mode, with the summary ``"<summary> · <distribution>"``.
    A command whose adapter fails to load, or whose parser fails to build,
    is skipped, logged, and returned as an omission so the failure is
    recorded once instead of retried on every new shell.
    """
    from sase.plugin_commands.adapter import (
        PluginCommandLoadError,
        load_plugin_command,
    )
    from sase.plugin_commands.registry import discover_plugin_commands

    builtin = build_spec()
    children = list(builtin.root.subcommands)
    omissions: list[PluginCommandOmission] = []
    for record in discover_plugin_commands().mounted:
        try:
            loaded = load_plugin_command(record)
        except PluginCommandLoadError as exc:
            omissions.append(
                PluginCommandOmission(
                    name=record.name,
                    distribution=record.distribution,
                    version=record.version,
                    reason=exc.cause,
                )
            )
            log.warning(
                "omitting plugin command %r from %s %s: %s",
                record.name,
                record.distribution,
                record.version,
                exc.cause,
            )
            continue
        try:
            parser = loaded.build_parser(prog=f"sase {record.name}")
            children.append(
                build_plugin_command(
                    parser,
                    name=record.name,
                    summary=f"{loaded.summary} · {record.distribution}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - a broken plugin never breaks completion.
            omissions.append(
                PluginCommandOmission(
                    name=record.name,
                    distribution=record.distribution,
                    version=record.version,
                    reason=f"could not build parser: {exc}",
                )
            )
            log.warning(
                "omitting plugin command %r from %s %s: could not build parser: %s",
                record.name,
                record.distribution,
                record.version,
                exc,
            )
            continue
    children.sort(key=lambda command: command.name)
    merged = CompletionSpec(
        prog=builtin.prog,
        version=builtin.version,
        root=replace(builtin.root, subcommands=tuple(children)),
    )
    return _RuntimeCompletionSpec(spec=merged, omissions=tuple(omissions))


__all__ = [
    "PluginCommandOmission",
    "_RuntimeCompletionSpec",
    "build_runtime_spec",
]
