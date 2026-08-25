"""Shared ``-p/--project`` resolution for ``sase memory`` CLI subcommands.

Reuses the project-record resolution already shared by
:func:`~sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project`
and the ACE glossary panel's project ring, which resolves a project ref (key,
name, alias, or CWD inference) to an enabled project's workspace directory
without requiring that project to have a glossary configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.xprompt._glossary_catalog_projects import select_project


class MemoryCliProjectError(RuntimeError):
    """Raised when a ``-p/--project`` ref cannot be resolved to a workspace."""


@dataclass(frozen=True, slots=True)
class _ResolvedMemoryCliProject:
    """A CLI-selected project's display name and workspace root."""

    project_name: str
    project_root: Path


def resolve_memory_cli_project(
    project_ref: str | None,
) -> _ResolvedMemoryCliProject | None:
    """Resolve *project_ref* to a workspace root, or ``None`` for the CWD default.

    Returns ``None`` when *project_ref* is not given, so callers keep their
    existing CWD-based root resolution unchanged. Raises
    :class:`MemoryCliProjectError` when a *project_ref* is given but does not
    resolve to an enabled, on-disk project.
    """
    if not project_ref:
        return None

    # Lazy import to avoid a circular dependency: glossary_catalog imports
    # sase.memory.web.catalog, whose package __init__ imports this module.
    from sase.xprompt.glossary_catalog import enabled_project_records

    records = enabled_project_records(None)
    project = select_project(project_ref, records, launch_workspace=None)
    if project is None:
        raise MemoryCliProjectError(
            f"project ref {project_ref!r} did not resolve to an enabled workspace"
        )
    return _ResolvedMemoryCliProject(
        project_name=project.name,
        project_root=project.workspace_dir,
    )


__all__ = [
    "MemoryCliProjectError",
    "resolve_memory_cli_project",
]
