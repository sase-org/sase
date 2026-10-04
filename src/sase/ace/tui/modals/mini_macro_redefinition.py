"""Shared analysis and warning copy for mini-macro redefinitions."""

from __future__ import annotations

from dataclasses import dataclass

from .mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroDestinationTarget,
    MiniMacroTargetCatalog,
    destination_target_for_name,
)
from .unified_macro_save_support import UnifiedSaveLocation


@dataclass(frozen=True, slots=True)
class MacroRedefinition:
    """Runtime and after-save resolution for one mini-macro destination."""

    name: str
    destination: MiniMacroDestinationTarget
    destination_definition: MiniMacroDefinition | None
    active: MiniMacroDefinition | None
    others: tuple[MiniMacroDefinition, ...]
    winner_after_save: str | None
    active_outside_rows: bool


def macro_redefinition(
    catalog: MiniMacroTargetCatalog,
    name: str,
    row: UnifiedSaveLocation,
) -> MacroRedefinition:
    """Resolve the active definition and the destination's post-save winner."""

    destination = destination_target_for_name(
        row,
        name,
        destinations=catalog.destinations,
    )
    definitions = catalog.definitions_for_name(name)
    destination_definition = next(
        (
            definition
            for definition in definitions
            if definition.location_path == row.location.path
        ),
        None,
    )
    active = next(
        (definition for definition in definitions if definition.effective), None
    )
    others = tuple(
        sorted(
            (
                definition
                for definition in definitions
                if definition is not destination_definition
            ),
            key=lambda definition: (
                not definition.effective,
                definition.precedence,
                definition.display_path,
                definition.entry_name or "",
            ),
        )
    )
    winner_after_save = _display_for_location(
        destination.resolution.shadowed_by,
        name,
        catalog,
    )
    row_paths = {
        destination_row.location.path for destination_row in catalog.destinations
    }
    active_outside_rows = active is not None and active.location_path not in row_paths
    return MacroRedefinition(
        name=name,
        destination=destination,
        destination_definition=destination_definition,
        active=active,
        others=others,
        winner_after_save=winner_after_save,
        active_outside_rows=active_outside_rows,
    )


def macro_redefinition_warning(redef: MacroRedefinition) -> str | None:
    """Return the shared warning copy, or ``None`` for a safe create/edit."""

    reference = f"#{redef.name}"
    destination = redef.destination.display_path
    destination_definition = redef.destination_definition
    if destination_definition is not None:
        if destination_definition.effective:
            return None
        winner = (
            destination_definition.shadowed_by
            or (redef.active.display_path if redef.active is not None else None)
            or redef.winner_after_save
            or "another definition"
        )
        return (
            f"⚠ {reference} in {destination_definition.display_path} is shadowed by "
            f"{winner} — edits here won't take effect"
        )

    active = redef.active
    if active is None:
        if redef.winner_after_save is None:
            return None
        winner = redef.winner_after_save
        return (
            f"⚠ {reference} already exists in {winner} — a copy in {destination} "
            f"would be shadowed by {winner} and won't take effect"
        )

    if redef.active_outside_rows:
        return (
            f"⚠ {reference} already exists in {active.display_path} — saving to "
            f"{destination} adds another definition"
        )
    if redef.winner_after_save is not None:
        return (
            f"⚠ {reference} already exists in {active.display_path} — a copy in "
            f"{destination} would be shadowed by {redef.winner_after_save} and "
            "won't take effect"
        )

    more_count = max(
        0,
        len(redef.others) - (1 if active in redef.others else 0),
    )
    more = f" (+{more_count} more)" if more_count else ""
    return (
        f"⚠ {reference} already exists in {active.display_path}{more} — saving to "
        f"{destination} will override it"
    )


def _display_for_location(
    location_path: str | None,
    name: str,
    catalog: MiniMacroTargetCatalog,
) -> str | None:
    if location_path is None:
        return None
    definition = next(
        (
            item
            for item in catalog.definitions_for_name(name)
            if item.location_path == location_path
        ),
        None,
    )
    if definition is not None:
        return definition.display_path
    row = next(
        (item for item in catalog.destinations if item.location.path == location_path),
        None,
    )
    return row.display_path if row is not None else location_path


__all__ = [
    "MacroRedefinition",
    "macro_redefinition",
    "macro_redefinition_warning",
]
