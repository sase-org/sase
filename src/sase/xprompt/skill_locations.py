"""Canonical destinations for authoring skill sources.

Authoring surfaces and the save writers share this module so a skill can only
ever be written where discovery will look for it.  A definition that declares
``skill:`` belongs in a canonical ``skills/`` directory, and an ordinary
prompt destination must refuse one; both halves read the same list from here.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.resources
from pathlib import Path

from sase.config import CHEZMOI_HOME, get_use_chezmoi
from sase.content_layout import (
    discover_project_root,
    resolve_chezmoi_layout,
    resolve_home_layout,
    resolve_project_layout,
)
from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

from .loader import detect_project
from .loader_skills import get_sase_package_skills_dir


@dataclass(frozen=True, slots=True)
class SkillDestination:
    """One canonical directory a new skill source may be written to."""

    label: str
    path: Path
    builtin: bool = False
    project_namespaced: bool = False
    """Whether ``#`` references to this scope carry the project namespace."""


def skill_destinations(project: str | None = None) -> list[SkillDestination]:
    """Return the canonical skill directories in discovery precedence order.

    The order mirrors :func:`sase.content_layout.resolve_skill_file_sources`
    for the writable scopes, followed by the package and plugin resource
    directories that are only writable in a development checkout.  Omitting
    *project* detects the current one, so the project-namespaced home scope is
    offered exactly where discovery would read it.
    """
    effective_project = project if project is not None else detect_project()
    home = Path.home()
    project_root = discover_project_root() or Path.cwd()
    project_skills = resolve_project_layout(project_root, home_root=home).skills.path
    home_skills = (
        resolve_chezmoi_layout(CHEZMOI_HOME, home_root=home).skills.path
        if get_use_chezmoi()
        else resolve_home_layout(home).skills.path
    )

    destinations = [
        SkillDestination(
            "Project sase/skills/", project_skills, project_namespaced=True
        ),
        SkillDestination("Home ~/sase/skills/", home_skills),
    ]
    if effective_project:
        destinations.append(
            SkillDestination(
                f"Project home ({effective_project})",
                home_skills / effective_project,
                project_namespaced=True,
            )
        )

    if not is_plugin_disabled("XPROMPTS"):
        for module in discover_plugin_resources("sase_xprompts"):
            try:
                resource = importlib.resources.files(module).joinpath("skills")
            except (TypeError, AttributeError):
                continue
            short_name = getattr(module, "__name__", str(module)).replace("_", "-")
            destinations.append(
                SkillDestination(
                    f"Plugin ({short_name}) skills/",
                    Path(str(resource)),
                    builtin=True,
                )
            )

    destinations.append(
        SkillDestination(
            "Built-in skills/", get_sase_package_skills_dir(), builtin=True
        )
    )
    return destinations


def is_canonical_skill_directory(
    directory: Path | str,
    *,
    project: str | None = None,
) -> bool:
    """Return whether *directory* is one of the canonical skill directories."""
    candidate = Path(directory).expanduser()
    return any(
        destination.path == candidate for destination in skill_destinations(project)
    )


__all__ = [
    "SkillDestination",
    "is_canonical_skill_directory",
    "skill_destinations",
]
