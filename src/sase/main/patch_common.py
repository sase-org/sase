"""Shared helpers for ``sase patch`` command handlers."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path

from sase.ace.patch import Patch


def command_name(args: argparse.Namespace) -> str:
    command = getattr(args, "command", "patch")
    return "patch" if command == "patch" else "patch"


def command_prefix(args: argparse.Namespace, subcommand: str) -> str:
    return f"sase {command_name(args)} {subcommand}"


def target_option(args: argparse.Namespace) -> str:
    return "-c/--changespec" if command_name(args) == "changespec" else "-p/--patch"


def patch_target(args: argparse.Namespace) -> str | None:
    return getattr(args, "patch", None) or getattr(args, "patch", None)


def _project_from_project_file(project_file: str | None) -> str | None:
    """Return the project basename for a main or archive project file path."""
    if not project_file:
        return None
    stem = Path(project_file).expanduser().stem
    if stem.endswith("-archive"):
        return stem[: -len("-archive")]
    return stem


def resolve_project_file(
    explicit: str | None,
    *,
    get_project_from_workspace_fn: Callable[[], str | None],
    get_project_file_path_fn: Callable[[str], str],
) -> str | None:
    """Resolve the project file path from --project-file or workspace inference."""
    if explicit:
        return os.path.expanduser(explicit)
    project = get_project_from_workspace_fn()
    if not project:
        return None
    return get_project_file_path_fn(project)


def resolve_project_context(
    explicit: str | None,
    *,
    get_project_from_workspace_fn: Callable[[], str | None],
    get_project_file_path_fn: Callable[[str], str],
) -> tuple[str | None, str | None]:
    """Resolve project and project-file context for ``patch current``."""
    if explicit:
        explicit_project_file = os.path.expanduser(explicit)
        return _project_from_project_file(explicit_project_file), explicit_project_file
    project = get_project_from_workspace_fn()
    project_file: str | None = get_project_file_path_fn(project) if project else None
    return project, project_file


def file_location(cs: Patch) -> str:
    """Return a user-facing file:line location."""
    file_path = cs.file_path.replace(str(Path.home()), "~")
    return f"{file_path}:{cs.line_number}"


__all__ = [
    "command_name",
    "command_prefix",
    "file_location",
    "patch_target",
    "resolve_project_context",
    "resolve_project_file",
    "target_option",
]
