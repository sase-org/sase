"""Target catalog for pane-scoped mini-macro authoring."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from sase.macro.loader import (
    detect_project,
    get_all_workflows,
    get_all_macros,
)
from sase.macro.loader_parsing import parse_macro_entries
from sase.macro.loader_sources import load_macro_from_file
from sase.macro.macro_sources import definition_file_for_source
from sase.macro.models import Macro
from sase.macro.naming import (
    ResolutionSource,
    SaveResolution,
    markdown_save_plan,
    resolution_after_save,
    validate_macro_name,
)
from sase.macro.prompt_frontmatter import PromptFrontmatter
from sase.macro.save import SaveTargetFormat
from sase.macro.segment_separators import macro_has_segment_separators
from sase.macro.write_targets import (
    MacroWriteTarget,
    resolve_macro_write_target,
    write_target_for_written_path,
)
from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

from .unified_macro_save_support import (
    UnifiedSaveLocation,
    load_unified_save_locations,
)
from .macro_location_modal import shorten_macro_location_path

MiniMacroWorkflowKind = Literal["macro", "workflow", "skill", "memory"]
MiniMacroCompatibility = Literal["editable", "read_only", "incompatible"]


@dataclass(frozen=True, slots=True)
class MiniMacroDefinition:
    """One physical or catalog-backed definition for a callable macro name."""

    name: str
    workflow_kind: MiniMacroWorkflowKind
    source_path: str | None
    display_path: str
    storage_format: SaveTargetFormat | None
    entry_name: str | None
    location_path: str | None
    precedence: int
    compatibility: MiniMacroCompatibility
    origin_label: str | None = None
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
class MiniMacroDestinationTarget:
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
class MiniMacroTargetCatalog:
    """Immutable snapshot of mini-macro definitions and writable targets."""

    definitions: tuple[MiniMacroDefinition, ...]
    destinations: tuple[UnifiedSaveLocation, ...]
    project: str | None = None
    _definitions_by_name: dict[str, tuple[MiniMacroDefinition, ...]] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        grouped: dict[str, list[MiniMacroDefinition]] = {}
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
                            not item.effective,
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

    def definitions_for_name(self, name: str) -> tuple[MiniMacroDefinition, ...]:
        return self._definitions_by_name.get(name, ())

    def effective_definition(self, name: str) -> MiniMacroDefinition | None:
        definitions = self.definitions_for_name(name)
        return definitions[0] if definitions else None


def load_mini_macro_target_catalog(
    project: str | None = None,
    *,
    locations: Sequence[UnifiedSaveLocation] | None = None,
) -> MiniMacroTargetCatalog:
    """Build a fresh mini-macro target catalog.

    Callers should run this off the Textual event loop. The returned catalog is
    names-and-metadata only; later phases load editable bodies separately.
    """

    effective_project = project if project is not None else detect_project()
    destination_rows = tuple(
        locations or load_unified_save_locations(effective_project)
    )
    macros = {
        name: replace(macro, source_path=_resolved_loader_source(macro.source_path))
        for name, macro in get_all_macros(project=effective_project).items()
    }
    definitions = list(_load_destination_definitions(destination_rows))
    definitions.extend(
        _load_catalog_only_definitions(
            effective_project,
            definitions,
            macros=macros,
        )
    )
    return MiniMacroTargetCatalog(
        definitions=_annotate_precedence(definitions, macros=macros),
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
    """Return the concrete path a mini-macro write would touch."""

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


def destination_defines_name(row: UnifiedSaveLocation, name: str) -> bool:
    """Return whether *row* already defines callable *name*."""

    return _collision_key_for_destination(row, name) in row.names


def destination_target_for_name(
    row: UnifiedSaveLocation,
    name: str,
    *,
    destinations: Sequence[UnifiedSaveLocation],
) -> MiniMacroDestinationTarget:
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
                destination_defines_name(candidate, name),
            )
            for candidate in sorted(destinations, key=lambda item: item.precedence)
        ],
    )
    return MiniMacroDestinationTarget(
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
        exists_here=destination_defines_name(row, name),
        resolution=resolution,
    )


def validate_name_for_destination(
    name: str,
    destination: UnifiedSaveLocation | None,
) -> str | None:
    """Validate *name* globally and against a namespaced destination."""

    error = validate_macro_name(name)
    if error is not None:
        return error
    if destination is not None and destination.namespace:
        prefix = f"{destination.namespace}/"
        if not name.startswith(prefix):
            return f"Names saved here must start with {prefix}"
        return validate_macro_name(name.removeprefix(prefix))
    return None


def rebase_name_for_destination(
    name: str,
    to_destination: UnifiedSaveLocation,
    *,
    from_destination: UnifiedSaveLocation | None = None,
) -> str:
    """Rebase *name* onto *to_destination*'s namespace.

    When *to_destination* has a namespace and the text lacks its ``<ns>/``
    prefix, the prefix is added. When moving away from a namespaced
    *from_destination*, that destination's prefix is stripped first. Empty
    names stay empty so the name step opens with a blank field.
    """

    remainder = name
    if from_destination is not None and from_destination.namespace:
        prefix = f"{from_destination.namespace}/"
        if remainder.startswith(prefix):
            remainder = remainder.removeprefix(prefix)
    if not remainder:
        return ""
    if to_destination.namespace:
        prefix = f"{to_destination.namespace}/"
        if not remainder.startswith(prefix):
            remainder = f"{prefix}{remainder}"
    return remainder


def mini_macro_prefix_matches(
    query: str,
    catalog: MiniMacroTargetCatalog,
    *,
    limit: int = 6,
) -> tuple[MiniMacroDefinition, ...]:
    """Return ranked prefix matches for the name modal."""

    if not query:
        return ()
    matches: list[tuple[tuple[object, ...], MiniMacroDefinition]] = []
    for ordinal, name in enumerate(catalog.names):
        if not name.startswith(query):
            continue
        definition = catalog.effective_definition(name)
        if definition is None:
            continue
        kind_rank = {
            "macro": 0,
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
) -> Iterable[MiniMacroDefinition]:
    for row in rows:
        if row.location.location_type == "directory":
            yield from _load_directory_definitions(row)
        else:
            yield from _load_config_definitions(row)


def _load_directory_definitions(
    row: UnifiedSaveLocation,
) -> Iterable[MiniMacroDefinition]:
    directory = Path(row.location.path)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        if not path.is_file():
            continue
        macro = load_macro_from_file(path)
        if macro is None:
            continue
        name = _callable_name(row, macro.name)
        compatibility, reason = _mini_compatibility(
            macro_has_segment_separators(macro),
            workflow_kind="macro",
            selectable=row.is_selectable and not row.builtin,
        )
        target = _existing_write_target(path) if compatibility == "editable" else None
        yield MiniMacroDefinition(
            name=name,
            workflow_kind="macro",
            source_path=str(path),
            display_path=_short_path(str(path)),
            storage_format=SaveTargetFormat.MARKDOWN,
            entry_name=None,
            location_path=row.location.path,
            precedence=row.precedence,
            compatibility=compatibility,
            origin_label=_origin_label(row, compatibility),
            incompatible_reason=reason,
            read_path=_path_attr(target, "read_path"),
            write_path=_path_attr(target, "write_path"),
            apply_target=_path_attr(target, "apply_target"),
            via_chezmoi=target.via_chezmoi if target is not None else False,
        )


def _load_config_definitions(
    row: UnifiedSaveLocation,
) -> Iterable[MiniMacroDefinition]:
    path = Path(row.location.path)
    if not path.is_file():
        return
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return
    if not isinstance(payload, dict):
        return
    try:
        entries = normalize_frontmatter_macros(payload, source=row.location.path)
    except ValueError:
        return
    parsed = parse_macro_entries(entries, row.location.path)
    for storage_name, macro in parsed.items():
        name = _callable_name(row, storage_name)
        compatibility, reason = _mini_compatibility(
            macro_has_segment_separators(macro),
            workflow_kind="macro",
            selectable=row.is_selectable and not row.builtin,
        )
        target = _existing_write_target(path) if compatibility == "editable" else None
        yield MiniMacroDefinition(
            name=name,
            workflow_kind="macro",
            source_path=str(path),
            display_path=f"{row.display_path}:{storage_name}",
            storage_format=SaveTargetFormat.CONFIG,
            entry_name=storage_name,
            location_path=row.location.path,
            precedence=row.precedence,
            compatibility=compatibility,
            origin_label=_origin_label(row, compatibility),
            incompatible_reason=reason,
            read_path=_path_attr(target, "read_path"),
            write_path=_path_attr(target, "write_path"),
            apply_target=_path_attr(target, "apply_target"),
            via_chezmoi=target.via_chezmoi if target is not None else False,
        )


def _load_catalog_only_definitions(
    project: str | None,
    existing: Sequence[MiniMacroDefinition],
    *,
    macros: Mapping[str, Macro] | None = None,
) -> Iterable[MiniMacroDefinition]:
    existing_keys = _normalized_definition_keys(existing)
    loaded_macros = macros if macros is not None else get_all_macros(project=project)
    ordinal = 0
    for name, macro in loaded_macros.items():
        workflow_kind: MiniMacroWorkflowKind | None = None
        reason: str | None = None
        if macro.skill_name is not None:
            workflow_kind = "skill"
            reason = "skills must be edited from the Macro Browser or skill source"
        elif macro.memory_type is not None:
            workflow_kind = "memory"
            reason = "memory definitions must be edited through memory notes"
        has_swarm_separator = macro_has_segment_separators(macro)
        if workflow_kind is None:
            workflow_kind = "macro"
            if has_swarm_separator:
                reason = "macro swarms cannot be opened as mini targets"
        source_path = macro.source_path
        yaml_source = source_path is not None and Path(source_path).suffix.lower() in {
            ".yml",
            ".yaml",
        }
        key = (name, _normalized_path(source_path))
        if key in existing_keys:
            continue
        compatibility: MiniMacroCompatibility = (
            "incompatible"
            if workflow_kind in {"skill", "memory"} or has_swarm_separator
            else "read_only"
        )
        yield MiniMacroDefinition(
            name=name,
            workflow_kind=workflow_kind,
            source_path=source_path,
            display_path=(
                f"{_short_path(source_path)}:{name}"
                if yaml_source and source_path is not None
                else _short_path(source_path or name)
            ),
            storage_format=SaveTargetFormat.CONFIG if yaml_source else None,
            entry_name=name if yaml_source else None,
            location_path=None,
            precedence=_catalog_only_precedence(existing, ordinal),
            compatibility=compatibility,
            origin_label="read-only",
            incompatible_reason=reason,
        )
        ordinal += 1
    existing_workflow_keys = {
        (definition.name, _normalized_path(definition.source_path))
        for definition in existing
        if definition.workflow_kind == "workflow"
    }
    for name, workflow in get_all_workflows(project=project).items():
        key = (name, _normalized_path(workflow.source_path))
        if key in existing_workflow_keys:
            continue
        yield MiniMacroDefinition(
            name=name,
            workflow_kind="workflow",
            source_path=workflow.source_path,
            display_path=_short_path(workflow.source_path or name),
            storage_format=None,
            entry_name=None,
            location_path=None,
            precedence=_catalog_only_precedence(existing, ordinal),
            compatibility="incompatible",
            origin_label="read-only",
            incompatible_reason=(
                "workflow graphs must be edited from the Macro Browser or source file"
            ),
        )
        ordinal += 1


def _annotate_precedence(
    definitions: Sequence[MiniMacroDefinition],
    *,
    macros: Mapping[str, Macro] | None = None,
) -> tuple[MiniMacroDefinition, ...]:
    by_name: dict[str, list[MiniMacroDefinition]] = {}
    for definition in definitions:
        by_name.setdefault(definition.name, []).append(definition)

    annotated: list[MiniMacroDefinition] = []
    for name, name_definitions in by_name.items():
        active_source = (macros or {}).get(name)
        active_match = _loader_matching_definition(name_definitions, active_source)
        ordered = sorted(
            name_definitions,
            key=lambda item: (
                0 if item is active_match else 1,
                item.precedence,
                item.display_path,
                item.entry_name or "",
            ),
        )
        for index, definition in enumerate(ordered):
            annotated.append(
                replace(
                    definition,
                    effective=index == 0,
                    shadowed_by=(
                        ordered[index - 1].display_path if index > 0 else None
                    ),
                    shadows=(
                        ordered[index + 1].display_path
                        if index + 1 < len(ordered)
                        else None
                    ),
                )
            )
    return tuple(
        sorted(
            annotated,
            key=lambda item: (
                item.name.casefold(),
                not item.effective,
                item.precedence,
                item.display_path,
                item.entry_name or "",
            ),
        )
    )


def _normalized_path(path: str | None) -> str | None:
    if path is None:
        return None
    write_path = resolve_macro_write_target(path).write_path
    return str(write_path.expanduser().resolve(strict=False))


def _resolved_loader_source(source: str | None) -> str | None:
    if not source or Path(source).is_absolute():
        return source
    resolved = definition_file_for_source(source)
    return str(resolved) if resolved is not None else source


def _normalized_definition_keys(
    definitions: Sequence[MiniMacroDefinition],
) -> set[tuple[str, str | None]]:
    return {
        (definition.name, _normalized_path(definition.source_path))
        for definition in definitions
    }


def _catalog_only_precedence(
    existing: Sequence[MiniMacroDefinition],
    ordinal: int,
) -> int:
    after_rows = max((definition.precedence for definition in existing), default=-1) + 1
    return max(1000, after_rows) + ordinal


def _loader_matching_definition(
    definitions: Sequence[MiniMacroDefinition],
    active_macro: Macro | None,
) -> MiniMacroDefinition | None:
    if active_macro is None or active_macro.source_path is None:
        return None
    active_path = _normalized_path(active_macro.source_path)
    matches = [
        definition
        for definition in definitions
        if _normalized_path(definition.source_path) == active_path
        and (
            definition.storage_format is not SaveTargetFormat.CONFIG
            or definition.entry_name == active_macro.name
            or definition.entry_name == definition.name
            or active_macro.name.endswith(f"/{definition.entry_name or ''}")
        )
    ]
    return min(
        matches,
        key=lambda item: (
            item.precedence,
            item.display_path,
            item.entry_name or "",
        ),
        default=None,
    )


def _origin_label(
    row: UnifiedSaveLocation,
    compatibility: MiniMacroCompatibility,
) -> str | None:
    if row.group == "Built-in (dev)":
        return "built-in"
    if row.group == "Plugin directories":
        return "plugin"
    if compatibility == "read_only":
        return "read-only"
    return None


def _mini_compatibility(
    has_swarm_separator: bool,
    *,
    workflow_kind: MiniMacroWorkflowKind,
    selectable: bool,
) -> tuple[MiniMacroCompatibility, str | None]:
    if workflow_kind != "macro":
        return "incompatible", f"{workflow_kind} definitions cannot be mini targets"
    if has_swarm_separator:
        return "incompatible", "macro swarms cannot be opened as mini targets"
    if not selectable:
        return "read_only", None
    return "editable", None


def _callable_name(row: UnifiedSaveLocation, storage_name: str) -> str:
    if row.namespace:
        return f"{row.namespace}/{storage_name}"
    return storage_name


def _existing_write_target(path: str | Path) -> MacroWriteTarget:
    return resolve_macro_write_target(path)


def _path_attr(target: MacroWriteTarget | None, attr: str) -> str | None:
    if target is None:
        return None
    value = getattr(target, attr)
    return str(value) if value is not None else None


def _short_path(path: str) -> str:
    return shorten_macro_location_path(path, str(Path.cwd()), str(Path.home()))


__all__ = [
    "MiniMacroCompatibility",
    "MiniMacroDefinition",
    "MiniMacroDestinationTarget",
    "MiniMacroTargetCatalog",
    "MiniMacroWorkflowKind",
    "destination_defines_name",
    "destination_target_for_name",
    "load_mini_macro_target_catalog",
    "mini_macro_prefix_matches",
    "rebase_name_for_destination",
    "validate_name_for_destination",
]
