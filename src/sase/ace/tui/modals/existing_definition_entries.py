"""Pure entries and ranking for the existing-definition finder."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.tui.modals.mini_macro_target_catalog import (
    MiniMacroDefinition,
    MiniMacroTargetCatalog,
)
from sase.core.fuzzy_facade import FuzzyMatch, fuzzy_match, fuzzy_sort_key
from sase.snippet.redefinition import SnippetDefinitionSite

ExistingStatus = Literal["active", "shadowed", "read_only", "incompatible"]
ExistingKind = Literal["macro", "snippet"]
ExistingVerdictKind = Literal["success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class ExistingDefinitionEntry:
    """One physical macro or snippet definition shown by the finder."""

    entry_id: str
    kind: ExistingKind
    name: str
    reference: str
    display_path: str
    origin_label: str | None
    status: ExistingStatus
    shadowed_by: str | None
    shadows: str | None
    reason: str | None
    precedence: int
    preview_text: str | None = None
    chip: str | None = None


@dataclass(frozen=True, slots=True)
class RankedExistingEntry:
    """An entry plus fuzzy runs for its name and display path."""

    entry: ExistingDefinitionEntry
    name_match: FuzzyMatch | None
    path_match: FuzzyMatch | None


def macro_existing_entries(
    catalog: MiniMacroTargetCatalog,
) -> tuple[ExistingDefinitionEntry, ...]:
    """Convert every physical macro catalog definition into a finder entry."""

    entries: list[ExistingDefinitionEntry] = []
    for definition in catalog.definitions:
        if definition.compatibility == "incompatible":
            status: ExistingStatus = "incompatible"
        elif definition.compatibility == "read_only":
            status = "read_only"
        elif definition.effective:
            status = "active"
        else:
            status = "shadowed"

        if definition.workflow_kind == "macro" and status == "incompatible":
            chip = "swarm"
        elif status == "read_only":
            chip = definition.origin_label or "read-only"
        elif status == "incompatible":
            chip = definition.workflow_kind
        else:
            chip = None
        origin = definition.origin_label
        if status == "read_only" and origin in {None, "read-only"}:
            origin = _macro_read_only_origin(definition)
            chip = origin
        if status == "incompatible":
            reason = definition.incompatible_reason or (
                f"{chip} definitions are not editable here"
            )
        elif status == "read_only":
            reason = origin or "read-only"
        else:
            reason = None
        entries.append(
            ExistingDefinitionEntry(
                entry_id=_macro_entry_id(definition),
                kind="macro",
                name=definition.name,
                reference=f"#{definition.name}",
                display_path=definition.display_path,
                origin_label=origin,
                status=status,
                shadowed_by=definition.shadowed_by,
                shadows=definition.shadows,
                reason=reason,
                precedence=definition.precedence,
                chip=chip,
            )
        )
    return tuple(entries)


def snippet_existing_entries(
    sites: Sequence[SnippetDefinitionSite],
) -> tuple[ExistingDefinitionEntry, ...]:
    """Convert provenance sites into entries, preserving catalog layer order."""

    entries: list[ExistingDefinitionEntry] = []
    shadowed_by_trigger: dict[str, list[SnippetDefinitionSite]] = {}
    for site in sites:
        if not site.active:
            shadowed_by_trigger.setdefault(site.trigger, []).append(site)
    for ordinal, site in enumerate(sites):
        status: ExistingStatus = (
            ("active" if site.active else "shadowed") if site.writable else "read_only"
        )
        origin = _snippet_origin(site)
        entries.append(
            ExistingDefinitionEntry(
                entry_id=_snippet_entry_id(site),
                kind="snippet",
                name=site.trigger,
                reference=f"⇥ {site.trigger}",
                display_path=site.display,
                origin_label=origin,
                status=status,
                shadowed_by=site.shadowed_by,
                shadows=(
                    shadowed_by_trigger[site.trigger][0].display
                    if site.active and shadowed_by_trigger.get(site.trigger)
                    else None
                ),
                reason=origin if status == "read_only" else None,
                # Contributions are listed in loader order, with later layers
                # winning. Negation makes a shadowed higher layer sort first.
                precedence=-ordinal,
                preview_text=site.template,
                chip=(
                    _snippet_chip(site, status)
                    if status in {"read_only", "incompatible"}
                    else None
                ),
            )
        )
    return tuple(entries)


def rank_existing_entries(
    entries: Sequence[ExistingDefinitionEntry],
    query: str,
    *,
    limit: int = 200,
) -> tuple[RankedExistingEntry, ...]:
    """Fuzzy-rank names first, then path-only matches, and cap the result."""

    if limit <= 0:
        return ()
    ranked: list[tuple[tuple[object, ...], RankedExistingEntry]] = []
    for entry in entries:
        if not query:
            row = RankedExistingEntry(entry, None, None)
            ranked.append((_empty_rank_key(entry), row))
            continue

        name_match = fuzzy_match(query, entry.name)
        path_match = fuzzy_match(query, entry.display_path)
        if name_match is None and path_match is None:
            continue
        if name_match is not None:
            key: tuple[object, ...] = (
                0,
                *fuzzy_sort_key(name_match, entry.name),
                *_entry_tiebreak(entry),
            )
        else:
            assert path_match is not None
            key = (
                1,
                *fuzzy_sort_key(path_match, entry.display_path),
                *_entry_tiebreak(entry),
            )
        ranked.append((key, RankedExistingEntry(entry, name_match, path_match)))
    ranked.sort(key=lambda item: item[0])
    return tuple(row for _, row in ranked[:limit])


def existing_entry_verdict(
    entry: ExistingDefinitionEntry,
) -> tuple[ExistingVerdictKind, str]:
    """Return the shared finder copy for the selected definition."""

    if entry.status == "active":
        return "success", f"✓ Edit {entry.reference} in place · {entry.display_path}"
    if entry.status == "shadowed":
        winner = entry.shadowed_by or "another definition"
        return (
            "warning",
            f"⚠ {entry.reference} in {entry.display_path} is shadowed by {winner} "
            "— edits here won't take effect",
        )
    if entry.status == "read_only":
        origin = entry.origin_label or "read-only"
        return (
            "warning",
            f"⚠ {entry.reference} is {origin} (read-only) — Enter picks where your "
            "override should live",
        )
    reason = entry.reason or "this definition is not a simple mini target"
    return "error", f"✗ Cannot open {entry.reference}: {reason}"


def _macro_entry_id(definition: MiniMacroDefinition) -> str:
    path = _normalize_path(definition.source_path or definition.location_path or "")
    return f"macro:{path}:{definition.entry_name or ''}:{definition.name}"


def _snippet_entry_id(site: SnippetDefinitionSite) -> str:
    layer = site.layer or site.kind
    path = _normalize_path(site.path or "")
    suffix = f":{site.macro_name}" if site.macro_name else ""
    return f"snippet:{layer}:{path}:{site.trigger}{suffix}"


def _normalize_path(path: str) -> str:
    if not path:
        return ""
    expanded = str(Path(path).expanduser())
    return os.path.normcase(os.path.normpath(expanded)).replace(os.sep, "/")


def _snippet_origin(site: SnippetDefinitionSite) -> str:
    if site.kind == "default" or site.layer == "default":
        return "built-in"
    if site.kind == "plugin" or (site.layer or "").startswith("plugin:"):
        module = (site.layer or "").removeprefix("plugin:")
        if not module and site.path:
            module = Path(site.path).stem
        return f"plugin {module or 'plugin'}"
    if site.kind in ("macro", "xprompt"):
        return f"from #{site.macro_name or site.trigger}"
    return site.kind


def _macro_read_only_origin(definition: MiniMacroDefinition) -> str:
    parts = Path(definition.source_path or "").parts
    if "default_macros" in parts:
        return "built-in"
    if "plugins" in parts:
        plugin_index = parts.index("plugins") + 1
        if plugin_index < len(parts):
            return f"plugin {parts[plugin_index]}"
    return "read-only"


def _snippet_chip(site: SnippetDefinitionSite, status: ExistingStatus) -> str:
    if status == "read_only":
        if site.kind in ("macro", "xprompt"):
            return "from #macro"
        if site.kind == "plugin":
            return "plugin"
        if site.kind == "default":
            return "built-in"
        return "read-only"
    return status


def _status_rank(status: ExistingStatus) -> int:
    return {"active": 0, "shadowed": 1, "read_only": 2, "incompatible": 3}[status]


def _entry_tiebreak(entry: ExistingDefinitionEntry) -> tuple[object, ...]:
    return (
        entry.status == "incompatible",
        entry.name.casefold(),
        _status_rank(entry.status),
        entry.precedence,
        entry.display_path.casefold(),
        entry.entry_id,
    )


def _empty_rank_key(entry: ExistingDefinitionEntry) -> tuple[object, ...]:
    return (
        entry.status == "incompatible",
        entry.name.casefold(),
        _status_rank(entry.status),
        entry.precedence,
        entry.display_path.casefold(),
        entry.entry_id,
    )


__all__ = [
    "ExistingDefinitionEntry",
    "ExistingKind",
    "ExistingStatus",
    "ExistingVerdictKind",
    "RankedExistingEntry",
    "existing_entry_verdict",
    "macro_existing_entries",
    "rank_existing_entries",
    "snippet_existing_entries",
]
