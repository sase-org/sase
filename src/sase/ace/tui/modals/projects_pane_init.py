"""Scope contract for Projects-tab ``sase init`` gestures.

This module is dependency-light and must not import Textual: scope construction
and argv mapping run before a worker is submitted and are unit-tested without
mounting an app.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.ace.tui.actions._durable_ops import sase_argv

INIT_CHECK_STARTUP_SECONDS = 30.0
INIT_CHECK_PER_PROJECT_SECONDS = 25.0
INIT_APPLY_STARTUP_SECONDS = 60.0
INIT_APPLY_PER_PROJECT_SECONDS = 180.0

_PROJECT_HEADING_PREFIX = "Project: "
_SUMMARY_PREFIX = "Initialization summary: "


@dataclass(frozen=True, slots=True)
class InitScope:
    """Selected project keys or the canonical all-projects inventory."""

    project_names: tuple[str, ...] = ()
    display_names: tuple[str, ...] = ()
    all_projects: bool = False

    @classmethod
    def for_projects(
        cls,
        names: Sequence[str],
        display_names: Sequence[str],
    ) -> InitScope:
        """Build a named-project scope from parallel directory keys and labels."""
        return cls(
            project_names=tuple(names),
            display_names=tuple(display_names),
            all_projects=False,
        )

    @classmethod
    def everything(cls) -> InitScope:
        """Build the canonical ``sase init --all`` inventory scope."""
        return cls(all_projects=True)

    @property
    def scope_key(self) -> str:
        """Stable dedup key: ``all``, or sorted directory keys joined by ``:``."""
        if self.all_projects:
            return "all"
        return ":".join(sorted(self.project_names))

    @property
    def label(self) -> str:
        """User-facing scope phrase for status lines and proc display names."""
        if self.all_projects:
            return "all projects"
        if len(self.display_names) == 1:
            return self.display_names[0]
        if len(self.project_names) == 1:
            return self.project_names[0]
        return f"{len(self.project_names)} projects"

    @property
    def cl_name(self) -> str:
        """Single project key for proc metadata; empty for multi/all scopes."""
        if self.all_projects or len(self.project_names) != 1:
            return ""
        return self.project_names[0]

    @property
    def scope_flags(self) -> tuple[str, ...]:
        """``--all`` or flattened ``-p NAME`` pairs in request order."""
        if self.all_projects:
            return ("--all",)
        flags: list[str] = []
        for name in self.project_names:
            flags.extend(("-p", name))
        return tuple(flags)

    def check_argv(self) -> list[str]:
        """Return ``sase init … --check --json`` for this scope."""
        return sase_argv("init", *self.scope_flags, "--check", "--json")

    def apply_argv(self) -> list[str]:
        """Return ``sase init … --yes`` for this scope."""
        return sase_argv("init", *self.scope_flags, "--yes")

    def terminal_argv(self) -> list[str]:
        """Return plain ``sase init …`` for this scope, for the interactive valve.

        No ``--yes``: the point of the terminal valve is the real ``[y/N/d]``
        and TTY-only prompts, not another non-interactive run.
        """
        return sase_argv("init", *self.scope_flags)


def init_cwd() -> Path:
    """Return the explicit cwd for init procs.

    The argv always carries ``-p`` or ``--all``, so cwd is never
    scoping-significant. The TUI must not manage cwd for project scoping.
    """
    return Path.home()


def check_timeout(count: int) -> float:
    """Return the check-proc timeout for ``max(count, 1)`` targets."""
    return INIT_CHECK_STARTUP_SECONDS + INIT_CHECK_PER_PROJECT_SECONDS * max(count, 1)


def apply_timeout(count: int) -> float:
    """Return the apply-proc timeout for ``max(count, 1)`` targets."""
    return INIT_APPLY_STARTUP_SECONDS + INIT_APPLY_PER_PROJECT_SECONDS * max(count, 1)


def parse_project_heading(line: str) -> str | None:
    """Return the coordinator ``Project: <ref>`` heading payload, if any."""
    stripped = line.strip()
    if not stripped.startswith(_PROJECT_HEADING_PREFIX):
        return None
    ref = stripped[len(_PROJECT_HEADING_PREFIX) :].strip()
    return ref or None


def parse_init_summary_line(output: str) -> str | None:
    """Return the last coordinator ``Initialization summary:`` payload, if any."""
    found: str | None = None
    for raw in output.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_SUMMARY_PREFIX):
            found = stripped[len(_SUMMARY_PREFIX) :].strip()
    return found or None


__all__ = [
    "INIT_APPLY_PER_PROJECT_SECONDS",
    "INIT_APPLY_STARTUP_SECONDS",
    "INIT_CHECK_PER_PROJECT_SECONDS",
    "INIT_CHECK_STARTUP_SECONDS",
    "InitScope",
    "apply_timeout",
    "check_timeout",
    "init_cwd",
    "parse_init_summary_line",
    "parse_project_heading",
]
