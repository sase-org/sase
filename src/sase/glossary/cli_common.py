"""Shared project resolution for ``sase glossary`` CLI subcommands."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.glossary_facade import CompiledGlossaryCatalog, GlossaryCatalog
from sase.xprompt.glossary_catalog import editor_glossary_catalog_for_project


class GlossaryCliError(RuntimeError):
    """Raised when a project or its glossary cannot be resolved for a CLI command."""


@dataclass(frozen=True, slots=True)
class ResolvedGlossaryProject:
    """A loaded glossary catalog scoped to one resolved project."""

    project_name: str
    catalog: GlossaryCatalog
    compiled: CompiledGlossaryCatalog
    config_path: str


def resolve_glossary_cli_project(project_ref: str | None) -> ResolvedGlossaryProject:
    """Resolve *project_ref* to a loaded glossary catalog.

    Raises :class:`GlossaryCliError` with a message distinguishing an unknown
    project, a project with no glossary configured, and an invalid glossary
    configuration.
    """
    result = editor_glossary_catalog_for_project(project_ref)
    if result.project is None:
        detail = result.diagnostics[0] if result.diagnostics else "no such project"
        raise GlossaryCliError(detail)
    if result.catalog is None:
        if result.diagnostics:
            raise GlossaryCliError("; ".join(result.diagnostics))
        raise GlossaryCliError(f"{result.project.name} has no glossary configured")
    return ResolvedGlossaryProject(
        project_name=result.project.name,
        catalog=result.catalog.catalog,
        compiled=result.catalog.compiled,
        config_path=str(result.catalog.config_path),
    )


__all__ = [
    "GlossaryCliError",
    "ResolvedGlossaryProject",
    "resolve_glossary_cli_project",
]
