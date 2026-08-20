"""Target catalog for pane-scoped mini-xprompt authoring."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from sase.xprompt.loader import (
    detect_project,
    get_all_workflows,
    get_all_xprompts,
)
from sase.xprompt.loader_parsing import parse_xprompt_entries
from sase.xprompt.loader_sources import load_xprompt_from_file
from sase.xprompt.naming import (
    ResolutionSource,
    SaveResolution,
    markdown_save_plan,
    resolution_after_save,
    validate_xprompt_name,
)
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.segment_separators import xprompt_has_segment_separators
from sase.xprompt.write_targets import (
    XPromptWriteTarget,
    resolve_xprompt_write_target,
    write_target_for_written_path,
)

from .unified_xprompt_save_support import (
    UnifiedSaveLocation,
    load_unified_save_locations,
)
from .xprompt_location_modal import shorten_xprompt_location_path

MiniXPromptWorkflowKind = Literal["xprompt", "workflow", "skill", "memory"]
MiniXPromptCompatibility = Literal["editable", "read_only", "incompatible"]


@dataclass(frozen=True, slots=True)
class MiniXPromptDefinition:
    """One physical or catalog-backed definition for a callable xprompt name."""

    name: str
    workflow_kind: MiniXPromptWorkflowKind
    source_path: str | None
    display_path: str
    storage_format: SaveTargetFormat | None
    entry_name: str | None
    location_path: str | None
    precedence: int
    compatibility: MiniXPromptCompatibility
    incompatible_reason: str | None = None
    effective: bool = False
    shadowed_by: str | None = None
    shadows: str | None = None
    read_path: str | None = None
    write_path: str | None = None
    apply_target: str | None = None
    via_chezmoi: bool = False

    @property
    def is_compatible(self) -> bool:
        return self.compatibility != "incompatible"

    @property
    def is_editable(self) -> bool:
        return self.compatibility == "editable"


@dataclass(frozen=True, slots=True)
class MiniXPromptDestinationTarget:
    """Concrete write target for a selected destination and typed name."""

    name: str
    location_path: str
    path: str
    display_path: str
    target_format: SaveTargetFormat
    entry_name: str | None
    storage_name: str
    read_path: str
    write_path: str
    apply_target: str | None
    via_chezmoi: bool
    exists_here: bool
    resolution: SaveResolution


@dataclass(frozen=True, slots=True)
class MiniXPromptTargetCatalog:
    """Immutable snapshot of mini-xprompt definitions and writable targets."""

    definitions: tuple[MiniXPromptDefinition, ...]
    destinations: tuple[UnifiedSaveLocation, ...]
    project: str | None = None
    _definitions_by_name: dict[str, tuple[MiniXPromptDefinition, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        grouped: dict[str, list[MiniXPromptDefinition]] = {}
        for definition in self.definitions:
            grouped.setdefault(definition.name, []).append(definition)
        object.__setattr__(
            self,
            "_definitions_by_name",
            {
                name: tuple(
                    sorted(
                        definitions,
                        key=lambda item: (
                            item.precedence,
                            item.display_path,
                            item.entry_name or "",
                        ),
                    )
                )
                for name, definitions in grouped.items()
            },
        )

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions_by_name))

    def definitions_for_name(self, name: str) -> tuple[MiniXPromptDefinition, ...]:
        return self._definitions_by_name.get(name, ())

    def effective_definition(self, name: str) -> MiniXPromptDefinition | None:
        definitions = self.definitions_for_name(name)
        return definitions[0] if definitions else None


def load_mini_xprompt_target_catalog(
    project: str | None = None,
    *,
    locations: Sequence[UnifiedSaveLocation] | None = None,
) -> MiniXPromptTargetCatalog:
    """Build a fresh mini-xprompt target catalog.

    Callers should run this off the Textual event loop. The returned catalog is
    names-and-metadata only; later phases load editable bodies separately.
    """

    effective_project = project if project is not None else detect_project()
    destination_rows = tuple(
        locations or load_unified_save_locations(effective_project)
    )
    definitions = list(_load_destination_definitions(destination_rows))
    definitions.extend(_load_catalog_only_definitions(effective_project, definitions))
    return MiniXPromptTargetCatalog(
        definitions=_annotate_precedence(definitions),
        destinations=destination_rows,
        project=effective_project,
    )


def _storage_name_for_destination(row: UnifiedSaveLocation, name: str) -> str:
    """Return the physical name written inside *row* for callable *name*."""

    if row.namespace:
        prefix = f"{row.namespace}/"
        if name.startswith(prefix):
            return name.removeprefix(prefix)
    return name


def _target_path_for_destination(row: UnifiedSaveLocation, name: str) -> str:
    """Return the concrete path a mini-xprompt write would touch."""

    storage_name = _storage_name_for_destination(row, name)
    if row.location.location_type == "directory":
        filename, _ = markdown_save_plan(storage_name, PromptFrontmatter())
        return str(Path(row.location.path) / filename)
    return row.location.path


def _collision_key_for_destination(row: UnifiedSaveLocation, name: str) -> str:
    """Return the names-only index key used for collision checks in *row*."""

    storage_name = _storage_name_for_destination(row, name)
    if row.location.location_type == "directory":
        filename, _ = markdown_save_plan(storage_name, PromptFrontmatter())
        return Path(filename).stem
    return storage_name


def _destination_defines_name(row: UnifiedSaveLocation, name: str) -> bool:
    """Return whether *row* already defines callable *name*."""

    return _collision_key_for_destination(row, name) in row.names


def destination_target_for_name(
    row: UnifiedSaveLocation,
    name: str,
    *,
    destinations: Sequence[UnifiedSaveLocation],
) -> MiniXPromptDestinationTarget:
    """Build the concrete write target for *name* at destination *row*."""

    storage_name = _storage_name_for_destination(row, name)
    path = _target_path_for_destination(row, name)
    write_target = write_target_for_written_path(path)
    target_format = (
        SaveTargetFormat.MARKDOWN
        if row.location.location_type == "directory"
        else SaveTargetFormat.CONFIG
    )
    entry_name = None if target_format is SaveTargetFormat.MARKDOWN else storage_name
    resolution = resolution_after_save(
        row.location.path,
        [
            ResolutionSource(
                candidate.location.path,
                _destination_defines_name(candidate, name),
            )
            for candidate in sorted(destinations, key=lambda item: item.precedence)
        ],
    )
    return MiniXPromptDestinationTarget(
        name=name,
        location_path=row.location.path,
        path=path,
        display_path=_short_path(path),
        target_format=target_format,
        entry_name=entry_name,
        storage_name=storage_name,
        read_path=str(write_target.read_path),
        write_path=str(write_target.write_path),
        apply_target=(
            str(write_target.apply_target)
            if write_target.apply_target is not None
            else None
        ),
        via_chezmoi=write_target.via_chezmoi,
        exists_here=_destination_defines_name(row, name),
        resolution=resolution,
    )


def validate_name_for_destination(
    name: str,
    destination: UnifiedSaveLocation | None,
) -> str | None:
    """Validate *name* globally and against a namespaced destination."""

    error = validate_xprompt_name(name)
    if error is not None:
        return error
    if destination is not None and destination.namespace:
        prefix = f"{destination.namespace}/"
        if not name.startswith(prefix):
            return f"Names saved here must start with {prefix}"
        return validate_xprompt_name(name.removeprefix(prefix))
    return None


def default_mini_xprompt_destination(
    catalog: MiniXPromptTargetCatalog,
    *,
    name: str = "",
    last_used_path: str | None = None,
) -> UnifiedSaveLocation | None:
    """Return the destination selected when the mini-name panel opens."""

    exact = catalog.effective_definition(name) if name else None
    if exact is not None and exact.is_editable and exact.location_path:
        match = _destination_by_path(catalog.destinations, exact.location_path)
        if match is not None and match.is_selectable:
            return match
    if last_used_path:
        match = _destination_by_path(catalog.destinations, last_used_path)
        if match is not None and match.is_selectable:
            return match
    for predicate in (
        lambda row: row.group == "Project",
        lambda row: row.location.label.startswith("Home "),
    ):
        match = next(
            (
                row
                for row in catalog.destinations
                if row.is_selectable and predicate(row)
            ),
            None,
        )
        if match is not None:
            return match
    return next((row for row in catalog.destinations if row.is_selectable), None)


def mini_xprompt_prefix_matches(
    query: str,
    catalog: MiniXPromptTargetCatalog,
    *,
    limit: int = 6,
) -> tuple[MiniXPromptDefinition, ...]:
    """Return ranked prefix matches for the name modal."""

    if not query:
        return ()
    matches: list[tuple[tuple[object, ...], MiniXPromptDefinition]] = []
    for ordinal, name in enumerate(catalog.names):
        if not name.startswith(query):
            continue
        definition = catalog.effective_definition(name)
        if definition is None:
            continue
        kind_rank = {
            "xprompt": 0,
            "workflow": 1,
            "skill": 2,
            "memory": 3,
        }[definition.workflow_kind]
        compatibility_rank = {
            "editable": 0,
            "read_only": 1,
            "incompatible": 2,
        }[definition.compatibility]
        matches.append(
            (
                (
                    name != query,
                    name.casefold(),
                    compatibility_rank,
                    kind_rank,
                    ordinal,
                ),
                definition,
            )
        )
    return tuple(item for _, item in sorted(matches, key=lambda item: item[0])[:limit])


def _load_destination_definitions(
    rows: Sequence[UnifiedSaveLocation],
) -> Iterable[MiniXPromptDefinition]:
    for row in rows:
        if row.location.location_type == "directory":
            yield from _load_directory_definitions(row)
        else:
            yield from _load_config_definitions(row)


def _load_directory_definitions(
    row: UnifiedSaveLocation,
) -> Iterable[MiniXPromptDefinition]:
    directory = Path(row.location.path)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        if not path.is_file():
            continue
        xprompt = load_xprompt_from_file(path)
        if xprompt is None:
            continue
        name = _callable_name(row, xprompt.name)
        compatibility, reason = _mini_compatibility(
            xprompt_has_segment_separators(xprompt),
            workflow_kind="xprompt",
            selectable=row.is_selectable and not row.builtin,
        )
        target = _existing_write_target(path) if compatibility == "editable" else None
        yield MiniXPromptDefinition(
            name=name,
            workflow_kind="xprompt",
            source_path=str(path),
            display_path=_short_path(str(path)),
            storage_format=SaveTargetFormat.MARKDOWN,
            entry_name=None,
            location_path=row.location.path,
            precedence=row.precedence,
            compatibility=compatibility,
            incompatible_reason=reason,
            read_path=_path_attr(target, "read_path"),
            write_path=_path_attr(target, "write_path"),
            apply_target=_path_attr(target, "apply_target"),
            via_chezmoi=target.via_chezmoi if target is not None else False,
        )


def _load_config_definitions(
    row: UnifiedSaveLocation,
) -> Iterable[MiniXPromptDefinition]:
    path = Path(row.location.path)
    if not path.is_file():
        return
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(payload, dict) or not isinstance(payload.get("xprompts"), dict):
        return
    parsed = parse_xprompt_entries(payload["xprompts"], row.location.path)
    for storage_name, xprompt in parsed.items():
        name = _callable_name(row, storage_name)
        compatibility, reason = _mini_compatibility(
            xprompt_has_segment_separators(xprompt),
            workflow_kind="xprompt",
            selectable=row.is_selectable and not row.builtin,
        )
        target = _existing_write_target(path) if compatibility == "editable" else None
        yield MiniXPromptDefinition(
            name=name,
            workflow_kind="xprompt",
            source_path=str(path),
            display_path=f"{row.display_path}:{storage_name}",
            storage_format=SaveTargetFormat.CONFIG,
            entry_name=storage_name,
            location_path=row.location.path,
            precedence=row.precedence,
            compatibility=compatibility,
            incompatible_reason=reason,
            read_path=_path_attr(target, "read_path"),
            write_path=_path_attr(target, "write_path"),
            apply_target=_path_attr(target, "apply_target"),
            via_chezmoi=target.via_chezmoi if target is not None else False,
        )


def _load_catalog_only_definitions(
    project: str | None,
    existing: Sequence[MiniXPromptDefinition],
) -> Iterable[MiniXPromptDefinition]:
    existing_keys = {
        (definition.name, definition.source_path, definition.workflow_kind)
        for definition in existing
    }
    for name, xprompt in get_all_xprompts(project=project).items():
        workflow_kind: MiniXPromptWorkflowKind | None = None
        reason: str | None = None
        if xprompt.skill_name is not None:
            workflow_kind = "skill"
            reason = "skills must be edited from the XPrompt Browser or skill source"
        elif xprompt.memory_type is not None:
            workflow_kind = "memory"
            reason = "memory definitions must be edited through memory notes"
        if workflow_kind is None:
            continue
        key = (name, xprompt.source_path, workflow_kind)
        if key in existing_keys:
            continue
        yield MiniXPromptDefinition(
            name=name,
            workflow_kind=workflow_kind,
            source_path=xprompt.source_path,
            display_path=_short_path(xprompt.source_path or name),
            storage_format=None,
            entry_name=None,
            location_path=None,
            precedence=xprompt.discovery_rank or 1000,
            compatibility="incompatible",
            incompatible_reason=reason,
        )
    for name, workflow in get_all_workflows(project=project).items():
        key = (name, workflow.source_path, "workflow")
        if key in existing_keys:
            continue
        yield MiniXPromptDefinition(
            name=name,
            workflow_kind="workflow",
            source_path=workflow.source_path,
            display_path=_short_path(workflow.source_path or name),
            storage_format=None,
            entry_name=None,
            location_path=None,
            precedence=workflow.discovery_rank or 1000,
            compatibility="incompatible",
            incompatible_reason=(
                "workflow graphs must be edited from the XPrompt Browser or source file"
            ),
        )


def _annotate_precedence(
    definitions: Sequence[MiniXPromptDefinition],
) -> tuple[MiniXPromptDefinition, ...]:
    by_name: dict[str, list[MiniXPromptDefinition]] = {}
    for definition in definitions:
        by_name.setdefault(definition.name, []).append(definition)

    annotated: list[MiniXPromptDefinition] = []
    for name_definitions in by_name.values():
        ordered = sorted(
            name_definitions,
            key=lambda item: (
                item.precedence,
                item.display_path,
                item.entry_name or "",
            ),
        )
        for index, definition in enumerate(ordered):
            annotated.append(
                MiniXPromptDefinition(
                    name=definition.name,
                    workflow_kind=definition.workflow_kind,
                    source_path=definition.source_path,
                    display_path=definition.display_path,
                    storage_format=definition.storage_format,
                    entry_name=definition.entry_name,
                    location_path=definition.location_path,
                    precedence=definition.precedence,
                    compatibility=definition.compatibility,
                    incompatible_reason=definition.incompatible_reason,
                    effective=index == 0,
                    shadowed_by=ordered[index - 1].display_path if index > 0 else None,
                    shadows=(
                        ordered[index + 1].display_path
                        if index + 1 < len(ordered)
                        else None
                    ),
                    read_path=definition.read_path,
                    write_path=definition.write_path,
                    apply_target=definition.apply_target,
                    via_chezmoi=definition.via_chezmoi,
                )
            )
    return tuple(
        sorted(
            annotated,
            key=lambda item: (
                item.name.casefold(),
                item.precedence,
                item.display_path,
                item.entry_name or "",
            ),
        )
    )


def _mini_compatibility(
    has_swarm_separator: bool,
    *,
    workflow_kind: MiniXPromptWorkflowKind,
    selectable: bool,
) -> tuple[MiniXPromptCompatibility, str | None]:
    if workflow_kind != "xprompt":
        return "incompatible", f"{workflow_kind} definitions cannot be mini targets"
    if has_swarm_separator:
        return "incompatible", "xprompt swarms cannot be opened as mini targets"
    if not selectable:
        return "read_only", None
    return "editable", None


def _callable_name(row: UnifiedSaveLocation, storage_name: str) -> str:
    if row.namespace:
        return f"{row.namespace}/{storage_name}"
    return storage_name


def _destination_by_path(
    rows: Sequence[UnifiedSaveLocation], path: str
) -> UnifiedSaveLocation | None:
    return next((row for row in rows if row.location.path == path), None)


def _existing_write_target(path: str | Path) -> XPromptWriteTarget:
    return resolve_xprompt_write_target(path)


def _path_attr(target: XPromptWriteTarget | None, attr: str) -> str | None:
    if target is None:
        return None
    value = getattr(target, attr)
    return str(value) if value is not None else None


def _short_path(path: str) -> str:
    return shorten_xprompt_location_path(path, str(Path.cwd()), str(Path.home()))


__all__ = [
    "MiniXPromptCompatibility",
    "MiniXPromptDefinition",
    "MiniXPromptDestinationTarget",
    "MiniXPromptTargetCatalog",
    "MiniXPromptWorkflowKind",
    "default_mini_xprompt_destination",
    "destination_target_for_name",
    "load_mini_xprompt_target_catalog",
    "mini_xprompt_prefix_matches",
    "validate_name_for_destination",
]
