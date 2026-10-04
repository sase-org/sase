"""Off-thread payload and loaders for the snippet location-first flow."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.modals.existing_definition_entries import (
    ExistingDefinitionEntry,
    snippet_existing_entries,
)
from sase.ace.tui.modals.save_location_choices import (
    EXISTING_CHOICE_ID,
    SNIPPET_CONFIGURED_SECTION,
    ExistingRowSpec,
    SaveLocationChoice,
    snippet_location_choices,
)
from sase.macro.snippet_targets import (
    SnippetConfigLocation,
    SnippetSaveTarget,
    snippet_save_target_for_location,
)
from sase.snippet.models import SnippetCatalog
from sase.snippet.redefinition import (
    SnippetDefinitionSite,
    snippet_definition_sites,
    snippet_redefinition,
)


@dataclass(frozen=True, slots=True)
class _PickerPayload:
    """Choices, save targets, and finder entries for one picker delivery."""

    choices: tuple[SaveLocationChoice, ...]
    targets: dict[str, SnippetSaveTarget]
    entries: tuple[ExistingDefinitionEntry, ...]
    sites_by_entry_id: dict[str, SnippetDefinitionSite]


def build_snippet_picker_payload(
    locations: tuple[SnippetConfigLocation, ...],
    resolved_target: SnippetSaveTarget,
    names_by_path: dict[str, frozenset[str]],
    last_used_path: str | None,
    current_path: str | None,
    project: str | None,
    trigger: str,
    catalog: SnippetCatalog | None,
    switching: bool,
    override_name: str | None,
) -> _PickerPayload:
    """Build picker choices, save-target map, and finder entries off-thread."""
    sites = snippet_definition_sites(catalog, locations) if catalog is not None else ()
    entries = snippet_existing_entries(sites)
    sites_by_entry_id = {
        entry.entry_id: site for site, entry in zip(sites, entries, strict=True)
    }
    existing = None
    shadowed_by: dict[str, str] | None = None
    if override_name is None:
        existing = ExistingRowSpec(
            count=len(catalog.entries) if catalog is not None else 0,
            switching=switching,
        )
    elif catalog is not None:
        shadowed_by = {}
        dest_paths = [location.path for location in locations]
        configured_path = str(resolved_target.write_path)
        if configured_path not in dest_paths:
            dest_paths.append(configured_path)
        for dest in dest_paths:
            winner = snippet_redefinition(
                catalog, override_name, dest, locations=locations
            ).winner_after_save
            if winner is not None:
                shadowed_by[dest] = winner.display
    choices, _default_id = snippet_location_choices(
        locations,
        resolved_target=resolved_target,
        names_by_path=names_by_path,
        last_used_path=last_used_path,
        current_path=current_path,
        project=project,
        trigger=trigger,
        existing=existing,
        override_name=override_name,
        shadowed_by=shadowed_by,
    )
    by_path = {location.path: location for location in locations}
    targets: dict[str, SnippetSaveTarget] = {}
    for choice in choices:
        if choice.choice_id == EXISTING_CHOICE_ID:
            continue
        if choice.section == SNIPPET_CONFIGURED_SECTION:
            targets[choice.choice_id] = resolved_target
            continue
        location = by_path.get(choice.choice_id)
        if location is None:
            targets[choice.choice_id] = resolved_target
        else:
            targets[choice.choice_id] = snippet_save_target_for_location(location)
    return _PickerPayload(choices, targets, entries, sites_by_entry_id)


def resolve_snippet_flow_target(configured: str) -> SnippetSaveTarget:
    """Resolve the configured snippet save target for one flow load."""
    from sase.macro.snippet_targets import resolve_snippet_save_target

    return resolve_snippet_save_target(configured)


def load_snippet_flow_locations(project: str | None) -> list[SnippetConfigLocation]:
    """Load discovered snippet config destinations for *project*."""
    from sase.macro.snippet_targets import load_snippet_config_locations

    return load_snippet_config_locations(project)


def load_snippet_flow_catalog(project: str | None) -> SnippetCatalog:
    """Load the provenance snippet catalog for *project*."""
    from sase.snippet.catalog import load_snippet_catalog

    return load_snippet_catalog(project)


def load_snippet_flow_last_used() -> str | None:
    """Return the last-used snippet config path, if any."""
    from sase.macro.save_state import load_last_used_locations

    return load_last_used_locations().get("snippet")


def load_snippet_flow_names(
    project: str | None,
    configured: str,
) -> dict[str, frozenset[str]]:
    """Return trigger names keyed by destination path."""
    from sase.macro.save_index import names_for_location

    locations = load_snippet_flow_locations(project)
    paths = [location.path for location in locations]
    try:
        configured_target = resolve_snippet_flow_target(configured)
    except Exception:
        configured_target = None
    if configured_target is not None:
        configured_path = str(configured_target.write_path)
        if configured_path not in paths:
            paths.append(configured_path)
    names: dict[str, frozenset[str]] = {}
    for path in paths:
        try:
            names[path] = names_for_location("snippet_config", path)
        except Exception:
            names[path] = frozenset()
    return names


__all__ = [
    "build_snippet_picker_payload",
    "load_snippet_flow_catalog",
    "load_snippet_flow_last_used",
    "load_snippet_flow_locations",
    "load_snippet_flow_names",
    "resolve_snippet_flow_target",
]
