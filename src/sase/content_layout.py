"""Canonical project/home content layout backed by :mod:`sase_core_rs`.

The Rust contract owns path names, compatibility policies, and xprompt source
ordering. This host adapter owns only filesystem concerns: finding a project
root, checking candidate presence, resolving symlinks, formatting paths, and
mapping home targets into a chezmoi source tree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from sase.core.content_layout_wire import (
    ChezmoiContentLayout,
    CompatibleLayoutPath,
    HomeContentLayout,
    LayoutCollisionError,
    LayoutPath,
    LayoutReadResolution,
    MemorySource,
    ProjectContentLayout,
    RefSource,
    SaseContentLayout,
    SkillPlacementIssue,
    SkillSource,
    XpromptSource,
    content_layout_from_mapping,
    skill_placement_issue_from_mapping,
)
from sase.core.rust import require_rust_binding

_PROJECT_MARKERS = (".git", ".hg", ".jj")


@dataclass(frozen=True)
class MemoryFileSource:
    """One memory-source record paired with its content root."""

    source: MemorySource
    root: Path

    @property
    def id(self) -> str:
        return self.source.id

    @property
    def scope(self) -> str:
        return self.source.scope

    @property
    def paths(self) -> CompatibleLayoutPath:
        return self.source.paths

    @property
    def formats(self) -> tuple[str, ...]:
        return self.source.formats

    def resolve_read_root(self, label: str) -> Path | None:
        """Return the selected canonical-or-legacy memory root."""
        return self.paths.resolve_read(label)


def _resolve_content_layout(
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    chezmoi_source_root: Path | str | None = None,
    project: str | None = None,
) -> SaseContentLayout:
    """Return the shared layout contract for explicit filesystem roots."""
    home = Path.home() if home_root is None else Path(home_root).expanduser()
    project_path = None if project_root is None else Path(project_root).expanduser()
    chezmoi_path = (
        None if chezmoi_source_root is None else Path(chezmoi_source_root).expanduser()
    )
    binding = require_rust_binding("sase_content_layout")
    payload: Mapping[str, Any] = binding(
        str(home),
        str(project_path) if project_path is not None else None,
        str(chezmoi_path) if chezmoi_path is not None else None,
        project,
    )
    return content_layout_from_mapping(payload)


def resolve_project_layout(
    root: Path | str,
    *,
    home_root: Path | str | None = None,
) -> ProjectContentLayout:
    """Return named canonical/legacy paths for one project root."""
    layout = _resolve_content_layout(project_root=root, home_root=home_root)
    if layout.project is None:  # pragma: no cover - guarded by explicit root
        raise RuntimeError("Rust layout omitted an explicit project root")
    return layout.project


def resolve_home_layout(root: Path | str | None = None) -> HomeContentLayout:
    """Return named canonical/legacy paths for the user's home root."""
    return _resolve_content_layout(home_root=root).home


def resolve_chezmoi_layout(
    source_root: Path | str,
    *,
    home_root: Path | str | None = None,
) -> ChezmoiContentLayout:
    """Return source-tree paths corresponding to the home layout."""
    layout = _resolve_content_layout(
        home_root=home_root,
        chezmoi_source_root=source_root,
    )
    if layout.chezmoi is None:  # pragma: no cover - guarded by explicit root
        raise RuntimeError("Rust layout omitted an explicit chezmoi source root")
    return layout.chezmoi


def discover_project_root(start: Path | str | None = None) -> Path | None:
    """Find the nearest VCS or SASE project root without shelling out.

    Symlinks are resolved before walking parents. Missing/deleted current
    directories return ``None`` instead of leaking ``FileNotFoundError``.
    Explicit missing descendants may still resolve through an existing parent.
    """
    if start is None:
        try:
            candidate = Path.cwd()
        except OSError:
            return None
    else:
        candidate = Path(start).expanduser()

    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    try:
        if resolved.is_file():
            resolved = resolved.parent
    except OSError:
        pass

    for parent in (resolved, *resolved.parents):
        if _is_project_root(parent):
            return parent
    return None


def resolve_project_config_read_path(
    root: Path | str,
    *,
    label: str = "project config",
) -> Path | None:
    """Return the canonical-or-legacy config read path for *root*.

    The shared layout contract deliberately treats project configuration as
    exclusive state.  When both locations exist this helper raises
    :class:`LayoutCollisionError` instead of silently merging them.
    """
    return resolve_project_layout(root).config.resolve_read(label)


def resolve_project_config_write_path(root: Path | str) -> Path:
    """Return the canonical project-config destination for *root*."""
    return resolve_project_layout(root).config.write_path


def resolve_xprompt_file_sources(
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    project: str | None = None,
) -> tuple[XpromptSource, ...]:
    """Return ordered filesystem-backed xprompt/workflow sources.

    The result is the Rust-owned first-wins order and includes canonical and
    compatibility directories.  When *project_root* is omitted, the nearest
    project containing the current directory is used so commands launched
    below a checkout root still see that project's content.
    """
    if project_root is None:
        root = discover_project_root()
        if root is None:
            try:
                root = Path.cwd()
            except OSError:
                root = None
    else:
        root = Path(project_root)
    layout = _resolve_content_layout(
        project_root=root,
        home_root=home_root,
        project=project,
    )
    return tuple(
        source
        for source in layout.xprompt_sources
        if source.path is not None
        and any(extension in source.formats for extension in ("md", "yml", "yaml"))
    )


def resolve_skill_file_sources(
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    project: str | None = None,
) -> tuple[SkillSource, ...]:
    """Return ordered filesystem-backed canonical skill sources.

    The Rust contract owns the first-wins order (project, home, project-
    specific home).  Package and plugin sources are resource locators without
    a filesystem path, so they are excluded here and loaded by their own
    ``importlib.resources`` loaders.  As with
    :func:`resolve_xprompt_file_sources`, omitting *project_root* falls back
    to the project containing the current directory.
    """
    if project_root is None:
        root = discover_project_root()
        if root is None:
            try:
                root = Path.cwd()
            except OSError:
                root = None
    else:
        root = Path(project_root)
    layout = _resolve_content_layout(
        project_root=root,
        home_root=home_root,
        project=project,
    )
    return tuple(source for source in layout.skill_sources if source.path is not None)


def resolve_ref_file_sources(
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    project: str | None = None,
    include_resource_sources: bool = False,
) -> tuple[RefSource, ...]:
    """Return ordered contextual ref renderer sources.

    Filesystem sources carry concrete paths for project, home, and
    project-specific home refs.  Package and plugin sources use resource
    locators and are included only when requested so filesystem callers do not
    accidentally treat them as directories.
    """
    if project_root is None:
        root = discover_project_root()
        if root is None:
            try:
                root = Path.cwd()
            except OSError:
                root = None
    else:
        root = Path(project_root)
    layout = _resolve_content_layout(
        project_root=root,
        home_root=home_root,
        project=project,
    )
    return tuple(
        source
        for source in layout.ref_sources
        if "md" in source.formats
        and (include_resource_sources or source.path is not None)
    )


def resolve_memory_file_sources(
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
    project: str | None = None,
    include_discovered_project: bool = True,
) -> tuple[MemoryFileSource, ...]:
    """Return ordered filesystem-backed xprompt-memory sources.

    The Rust contract owns the ordered memory source records. This adapter only
    pairs each record with the project or home content root needed by the
    canonical memory note parser.
    """
    if project_root is None:
        if include_discovered_project:
            root = discover_project_root()
            if root is None:
                try:
                    root = Path.cwd()
                except OSError:
                    root = None
        else:
            root = None
    else:
        root = Path(project_root)

    layout = _resolve_content_layout(
        project_root=root,
        home_root=home_root,
        project=project,
    )
    roots: dict[str, Path] = {"home": layout.home.root}
    if layout.project is not None:
        roots["project"] = layout.project.root

    sources: list[MemoryFileSource] = []
    for source in layout.memory_sources:
        if "md" not in source.formats:
            continue
        source_root = roots.get(source.scope)
        if source_root is None:
            continue
        sources.append(MemoryFileSource(source=source, root=source_root))
    return tuple(sources)


def skill_reference_name(skill_name: str, project: str | None = None) -> str:
    """Return the canonical ``skill/<name>`` xprompt reference for a skill.

    The provider-visible skill name is unchanged; only the xprompt reference
    is namespaced, so ``#skill/foo`` expands what ``/foo`` invokes.
    """
    binding = require_rust_binding("skill_reference_name")
    return str(binding(skill_name, project))


def memory_reference_name(stem: str) -> str:
    """Return the canonical ``memory/<stem>`` xprompt reference."""
    binding = require_rust_binding("memory_reference_name")
    return str(binding(stem))


def memory_note_issue(
    source: Path | str,
    *,
    stem: str,
    note_type: str,
) -> SkillPlacementIssue | None:
    """Apply the shared xprompt-memory note eligibility rule."""
    binding = require_rust_binding("memory_note_issue")
    payload: Mapping[str, Any] | None = binding(str(source), stem, note_type)
    if payload is None:
        return None
    return skill_placement_issue_from_mapping(payload)


def reserved_memory_namespace_issue(
    source: Path | str,
    reference: str,
) -> SkillPlacementIssue | None:
    """Return a diagnostic when an ordinary definition claims ``memory/``."""
    binding = require_rust_binding("reserved_memory_namespace_issue")
    payload: Mapping[str, Any] | None = binding(str(source), reference)
    if payload is None:
        return None
    return skill_placement_issue_from_mapping(payload)


def skill_placement_issue(
    source: Path | str,
    *,
    in_skill_source: bool,
    declares_skill: bool,
    migrate_to: Path | str | None = None,
) -> SkillPlacementIssue | None:
    """Apply the shared two-way skill placement rule to one definition.

    Returns ``None`` when placement is valid: a canonical skill source that
    declares a truthy ``skill`` value, or an ordinary source that declares
    none.
    """
    binding = require_rust_binding("skill_placement_issue")
    payload: Mapping[str, Any] | None = binding(
        str(source),
        in_skill_source,
        declares_skill,
        None if migrate_to is None else str(migrate_to),
    )
    if payload is None:
        return None
    return skill_placement_issue_from_mapping(payload)


def chezmoi_source_path(
    target: Path | str,
    *,
    home_root: Path | str | None = None,
    source_root: Path | str | None = None,
) -> Path:
    """Map one home target to chezmoi's source naming convention."""
    path = Path(target).expanduser()
    home = Path.home() if home_root is None else Path(home_root).expanduser()
    source = (
        Path("~/.local/share/chezmoi/home").expanduser()
        if source_root is None
        else Path(source_root).expanduser()
    )
    try:
        relative = path.relative_to(home)
    except ValueError:
        return path
    encoded = (
        f"dot_{part[1:]}" if part.startswith(".") else part for part in relative.parts
    )
    return source.joinpath(*encoded)


def display_path(
    path: Path | str,
    *,
    project_root: Path | str | None = None,
    home_root: Path | str | None = None,
) -> str:
    """Render a project-relative or ``~/`` path without substring replacement."""
    raw = Path(path).expanduser()
    normalized = _normalized(raw)
    if project_root is not None:
        project = _normalized(Path(project_root).expanduser())
        relative = _relative_to(normalized, project)
        if relative is not None:
            return "." if relative == Path(".") else relative.as_posix()

    home = _normalized(
        Path.home() if home_root is None else Path(home_root).expanduser()
    )
    relative = _relative_to(normalized, home)
    if relative is not None:
        return "~" if relative == Path(".") else f"~/{relative.as_posix()}"
    return raw.as_posix()


def _is_project_root(path: Path) -> bool:
    try:
        if any((path / marker).exists() for marker in _PROJECT_MARKERS):
            return True
        return (path / "sase" / "sase.yml").is_file() or (path / "sase.yml").is_file()
    except OSError:
        return False


def _normalized(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return Path(os.path.abspath(os.fspath(path)))


def _relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


__all__ = [
    "ChezmoiContentLayout",
    "CompatibleLayoutPath",
    "HomeContentLayout",
    "LayoutCollisionError",
    "LayoutPath",
    "LayoutReadResolution",
    "MemoryFileSource",
    "MemorySource",
    "ProjectContentLayout",
    "RefSource",
    "SaseContentLayout",
    "SkillPlacementIssue",
    "SkillSource",
    "XpromptSource",
    "chezmoi_source_path",
    "discover_project_root",
    "display_path",
    "resolve_chezmoi_layout",
    "resolve_project_config_read_path",
    "resolve_project_config_write_path",
    "resolve_home_layout",
    "resolve_memory_file_sources",
    "resolve_project_layout",
    "resolve_ref_file_sources",
    "resolve_skill_file_sources",
    "resolve_xprompt_file_sources",
    "memory_note_issue",
    "memory_reference_name",
    "reserved_memory_namespace_issue",
    "skill_placement_issue",
    "skill_reference_name",
]
