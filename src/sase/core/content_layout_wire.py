"""Typed Python mirrors for the Rust SASE content-layout wire."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from sase.core.rust import require_rust_binding

PathRole = Literal["canonical", "legacy", "unchanged"]
PathTracking = Literal[
    "source_controlled",
    "generated",
    "runtime_only",
    "user_config",
    "package_owned",
]
CollisionPolicy = Literal["error", "first_wins"]


class LayoutCollisionError(ValueError):
    """Canonical and legacy paths coexist under an exclusive read policy."""

    def __init__(self, label: str, paths: tuple[Path, ...]) -> None:
        self.label = label
        self.paths = paths
        rendered = ", ".join(str(path) for path in paths)
        super().__init__(
            f"{label} exists in multiple canonical/legacy locations: {rendered}; "
            "migrate to the canonical path instead of merging split state"
        )


@dataclass(frozen=True)
class LayoutPath:
    path: Path
    role: PathRole
    tracking: PathTracking


@dataclass(frozen=True)
class LayoutReadResolution:
    selected: Path | None
    existing: tuple[Path, ...]
    shadowed: tuple[Path, ...]
    collision: bool


@dataclass(frozen=True)
class CompatibleLayoutPath:
    canonical: LayoutPath
    legacy: tuple[LayoutPath, ...]
    write_path: Path
    read_policy: CollisionPolicy

    @property
    def candidates(self) -> tuple[Path, ...]:
        return (self.canonical.path, *(entry.path for entry in self.legacy))

    def resolve(
        self,
        *,
        exists: Callable[[Path], bool] | None = None,
    ) -> LayoutReadResolution:
        """Resolve existing candidates using the core collision policy."""
        predicate = exists or Path.exists
        candidates = self.candidates
        presence = [predicate(path) for path in candidates]
        binding = require_rust_binding("resolve_layout_candidates")
        payload: Mapping[str, Any] = binding(self.read_policy, presence)
        existing_indices = tuple(
            int(index) for index in payload.get("existing_indices", ())
        )
        shadowed_indices = tuple(
            int(index) for index in payload.get("shadowed_indices", ())
        )
        raw_selected = payload.get("selected_index")
        selected_index = int(raw_selected) if raw_selected is not None else None
        return LayoutReadResolution(
            selected=(
                candidates[selected_index] if selected_index is not None else None
            ),
            existing=tuple(candidates[index] for index in existing_indices),
            shadowed=tuple(candidates[index] for index in shadowed_indices),
            collision=bool(payload.get("collision", False)),
        )

    def resolve_read(
        self,
        label: str,
        *,
        exists: Callable[[Path], bool] | None = None,
    ) -> Path | None:
        """Return the selected read path or raise a split-state diagnostic."""
        resolution = self.resolve(exists=exists)
        if resolution.collision:
            raise LayoutCollisionError(label, resolution.existing)
        return resolution.selected


@dataclass(frozen=True)
class ProjectContentLayout:
    root: Path
    namespace_root: LayoutPath
    config: CompatibleLayoutPath
    xprompts: CompatibleLayoutPath
    skills: LayoutPath
    refs: LayoutPath
    memory: CompatibleLayoutPath
    repos: LayoutPath
    memory_readme: LayoutPath
    agent_documents: tuple[LayoutPath, ...]


@dataclass(frozen=True)
class HomeContentLayout:
    root: Path
    namespace_root: LayoutPath
    xprompts: CompatibleLayoutPath
    skills: LayoutPath
    refs: LayoutPath
    memory: CompatibleLayoutPath
    global_config: LayoutPath
    state_root: LayoutPath
    memory_readme: LayoutPath
    agent_documents: tuple[LayoutPath, ...]


@dataclass(frozen=True)
class ChezmoiContentLayout:
    source_root: Path
    namespace_root: LayoutPath
    xprompts: CompatibleLayoutPath
    skills: LayoutPath
    refs: LayoutPath
    memory: CompatibleLayoutPath
    global_config: LayoutPath
    memory_readme: LayoutPath
    agent_documents: tuple[LayoutPath, ...]


@dataclass(frozen=True)
class XpromptSource:
    id: str
    priority: int
    scope: str
    role: PathRole
    locator: str
    path: Path | None
    formats: tuple[str, ...]
    steps_locator: str | None
    project_namespaced: bool
    writable: bool
    collision_group: str | None
    collision_policy: CollisionPolicy | None
    ordering: str | None

    @property
    def steps_path(self) -> Path | None:
        if self.path is None or self.steps_locator is None:
            return None
        return Path(self.steps_locator)


@dataclass(frozen=True)
class SkillSource:
    """One ordered, first-wins source of canonical skill definitions.

    Skill sources are a separate, narrower contract than
    :class:`XpromptSource`: they carry no legacy candidates and no shared
    ``steps/`` directory, and package/plugin entries are resource locators
    rather than filesystem paths.
    """

    id: str
    priority: int
    scope: str
    locator: str
    path: Path | None
    formats: tuple[str, ...]
    tracking: PathTracking
    project_namespaced: bool
    writable: bool
    ordering: str | None


@dataclass(frozen=True)
class MemorySource:
    """One ordered source of flat SASE memory notes exposed as xprompts."""

    id: str
    priority: int
    scope: str
    paths: CompatibleLayoutPath
    formats: tuple[str, ...]
    tracking: PathTracking
    writable: bool
    ordering: str | None


@dataclass(frozen=True)
class SkillPlacementIssue:
    """One definition rejected by the shared skill placement rules."""

    source: str
    rule: str
    message: str
    migrate_to: str | None


@dataclass(frozen=True)
class SaseContentLayout:
    schema_version: int
    project: ProjectContentLayout | None
    home: HomeContentLayout
    chezmoi: ChezmoiContentLayout | None
    xprompt_sources: tuple[XpromptSource, ...]
    skill_sources: tuple[SkillSource, ...]
    memory_sources: tuple[MemorySource, ...]


def content_layout_from_mapping(raw: Mapping[str, Any]) -> SaseContentLayout:
    schema_version = int(raw["schema_version"])
    if schema_version < 5:
        raise RuntimeError(
            "sase_core_rs content-layout wire is stale: "
            f"expected schema >= 5 for ref sources, got {schema_version}"
        )
    project_raw = raw.get("project")
    chezmoi_raw = raw.get("chezmoi")
    return SaseContentLayout(
        schema_version=schema_version,
        project=(
            _project_layout(_mapping(project_raw)) if project_raw is not None else None
        ),
        home=_home_layout(_mapping(raw["home"])),
        chezmoi=(
            _chezmoi_layout(_mapping(chezmoi_raw)) if chezmoi_raw is not None else None
        ),
        xprompt_sources=tuple(
            _xprompt_source(_mapping(item))
            for item in cast(list[Any], raw.get("xprompt_sources", []))
        ),
        skill_sources=tuple(
            _skill_source(_mapping(item))
            for item in cast(list[Any], raw.get("skill_sources", []))
        ),
        memory_sources=tuple(
            _memory_source(_mapping(item))
            for item in cast(list[Any], raw.get("memory_sources", []))
        ),
    )


def _layout_path(raw: Mapping[str, Any]) -> LayoutPath:
    return LayoutPath(
        path=Path(str(raw["path"])),
        role=cast(PathRole, raw["role"]),
        tracking=cast(PathTracking, raw["tracking"]),
    )


def _compatible_path(raw: Mapping[str, Any]) -> CompatibleLayoutPath:
    return CompatibleLayoutPath(
        canonical=_layout_path(_mapping(raw["canonical"])),
        legacy=tuple(
            _layout_path(_mapping(item))
            for item in cast(list[Any], raw.get("legacy", []))
        ),
        write_path=Path(str(raw["write_path"])),
        read_policy=cast(CollisionPolicy, raw["read_policy"]),
    )


def _project_layout(raw: Mapping[str, Any]) -> ProjectContentLayout:
    return ProjectContentLayout(
        root=Path(str(raw["root"])),
        namespace_root=_layout_path(_mapping(raw["namespace_root"])),
        config=_compatible_path(_mapping(raw["config"])),
        xprompts=_compatible_path(_mapping(raw["xprompts"])),
        skills=_layout_path(_mapping(raw["skills"])),
        refs=_layout_path(_mapping(raw["refs"])),
        memory=_compatible_path(_mapping(raw["memory"])),
        repos=_layout_path(_mapping(raw["repos"])),
        memory_readme=_layout_path(_mapping(raw["memory_readme"])),
        agent_documents=_layout_paths(raw.get("agent_documents", [])),
    )


def _home_layout(raw: Mapping[str, Any]) -> HomeContentLayout:
    return HomeContentLayout(
        root=Path(str(raw["root"])),
        namespace_root=_layout_path(_mapping(raw["namespace_root"])),
        xprompts=_compatible_path(_mapping(raw["xprompts"])),
        skills=_layout_path(_mapping(raw["skills"])),
        refs=_layout_path(_mapping(raw["refs"])),
        memory=_compatible_path(_mapping(raw["memory"])),
        global_config=_layout_path(_mapping(raw["global_config"])),
        state_root=_layout_path(_mapping(raw["state_root"])),
        memory_readme=_layout_path(_mapping(raw["memory_readme"])),
        agent_documents=_layout_paths(raw.get("agent_documents", [])),
    )


def _chezmoi_layout(raw: Mapping[str, Any]) -> ChezmoiContentLayout:
    return ChezmoiContentLayout(
        source_root=Path(str(raw["source_root"])),
        namespace_root=_layout_path(_mapping(raw["namespace_root"])),
        xprompts=_compatible_path(_mapping(raw["xprompts"])),
        skills=_layout_path(_mapping(raw["skills"])),
        refs=_layout_path(_mapping(raw["refs"])),
        memory=_compatible_path(_mapping(raw["memory"])),
        global_config=_layout_path(_mapping(raw["global_config"])),
        memory_readme=_layout_path(_mapping(raw["memory_readme"])),
        agent_documents=_layout_paths(raw.get("agent_documents", [])),
    )


def _xprompt_source(raw: Mapping[str, Any]) -> XpromptSource:
    path = raw.get("path")
    return XpromptSource(
        id=str(raw["id"]),
        priority=int(raw["priority"]),
        scope=str(raw["scope"]),
        role=cast(PathRole, raw["role"]),
        locator=str(raw["locator"]),
        path=Path(str(path)) if path is not None else None,
        formats=tuple(str(item) for item in raw.get("formats", [])),
        steps_locator=(
            str(raw["steps_path"]) if raw.get("steps_path") is not None else None
        ),
        project_namespaced=bool(raw.get("project_namespaced", False)),
        writable=bool(raw.get("writable", False)),
        collision_group=(
            str(raw["collision_group"])
            if raw.get("collision_group") is not None
            else None
        ),
        collision_policy=cast(CollisionPolicy | None, raw.get("collision_policy")),
        ordering=(str(raw["ordering"]) if raw.get("ordering") is not None else None),
    )


def _skill_source(raw: Mapping[str, Any]) -> SkillSource:
    path = raw.get("path")
    return SkillSource(
        id=str(raw["id"]),
        priority=int(raw["priority"]),
        scope=str(raw["scope"]),
        locator=str(raw["locator"]),
        path=Path(str(path)) if path is not None else None,
        formats=tuple(str(item) for item in raw.get("formats", [])),
        tracking=cast(PathTracking, raw["tracking"]),
        project_namespaced=bool(raw.get("project_namespaced", False)),
        writable=bool(raw.get("writable", False)),
        ordering=(str(raw["ordering"]) if raw.get("ordering") is not None else None),
    )


def _memory_source(raw: Mapping[str, Any]) -> MemorySource:
    return MemorySource(
        id=str(raw["id"]),
        priority=int(raw["priority"]),
        scope=str(raw["scope"]),
        paths=_compatible_path(_mapping(raw["paths"])),
        formats=tuple(str(item) for item in raw.get("formats", [])),
        tracking=cast(PathTracking, raw["tracking"]),
        writable=bool(raw.get("writable", False)),
        ordering=(str(raw["ordering"]) if raw.get("ordering") is not None else None),
    )


def skill_placement_issue_from_mapping(
    raw: Mapping[str, Any],
) -> SkillPlacementIssue:
    """Build the typed placement issue returned by the Rust rule."""
    migrate_to = raw.get("migrate_to")
    return SkillPlacementIssue(
        source=str(raw["source"]),
        rule=str(raw["rule"]),
        message=str(raw["message"]),
        migrate_to=str(migrate_to) if migrate_to is not None else None,
    )


def _layout_paths(raw: Any) -> tuple[LayoutPath, ...]:
    return tuple(_layout_path(_mapping(item)) for item in cast(list[Any], raw))


def _mapping(raw: Any) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"expected layout mapping, got {type(raw).__name__}")
    return cast(Mapping[str, Any], raw)


__all__ = [
    "ChezmoiContentLayout",
    "CompatibleLayoutPath",
    "HomeContentLayout",
    "LayoutCollisionError",
    "LayoutPath",
    "LayoutReadResolution",
    "MemorySource",
    "ProjectContentLayout",
    "SaseContentLayout",
    "SkillPlacementIssue",
    "SkillSource",
    "XpromptSource",
    "content_layout_from_mapping",
    "skill_placement_issue_from_mapping",
]
