"""Provenance-accurate snippet redefinition analysis and shared warning copy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.macro.snippet_targets import SnippetConfigLocation
from sase.macro.write_targets import resolve_macro_write_target
from sase.snippet.models import (
    SnippetCatalog,
    SnippetSourceContribution,
    SnippetSourceKind,
    is_macro_derived_kind,
)

_MACRO_DERIVED_RANK = -1
_OUT_OF_DISCOVERY_RANK = 10_000
_KIND_FALLBACK_RANK = {
    "default": 0,
    "plugin": 1,
    "user": 2,
    "overlay": 3,
    "project": 4,
    "configured": _OUT_OF_DISCOVERY_RANK,
    "pending": _OUT_OF_DISCOVERY_RANK - 1,
}


@dataclass(frozen=True, slots=True)
class SnippetDefinitionSite:
    """One physical definition of a trigger across the provenance catalog."""

    trigger: str
    kind: SnippetSourceKind
    path: str | None
    display: str
    template: str
    writable: bool
    active: bool
    shadowed_by: str | None
    layer: str | None = None
    macro_name: str | None = None


@dataclass(frozen=True, slots=True)
class SnippetRedefinition:
    """Where *trigger* lives today and what saving to *destination_path* would do."""

    trigger: str
    destination_path: str
    destination_site: SnippetDefinitionSite | None
    active: SnippetDefinitionSite | None
    others: tuple[SnippetDefinitionSite, ...]
    winner_after_save: SnippetDefinitionSite | None
    alias_of: str | None


def snippet_definition_sites(
    catalog: SnippetCatalog,
    locations: Sequence[SnippetConfigLocation] | None = None,
) -> tuple[SnippetDefinitionSite, ...]:
    """Return every authored definition in the catalog as a ranked site."""
    writable_paths = _writable_location_paths(locations)
    sites: list[SnippetDefinitionSite] = []
    for entry in catalog.entries:
        origin = entry.origin
        for contribution in entry.contributions:
            active = _same_source(contribution, origin)
            sites.append(
                _site_from_contribution(
                    contribution,
                    active=active,
                    winner_display=_site_display(origin) if not active else None,
                    writable_paths=writable_paths,
                )
            )
    return tuple(sites)


def snippet_redefinition(
    catalog: SnippetCatalog,
    trigger: str,
    destination_path: str,
    locations: Sequence[SnippetConfigLocation] | None = None,
) -> SnippetRedefinition:
    """Analyze saving *trigger* to *destination_path* against the catalog."""
    sites = tuple(
        site
        for site in snippet_definition_sites(catalog, locations)
        if site.trigger == trigger
    )
    dest_site = next(
        (
            site
            for site in sites
            if _path_matches_destination(site.path, destination_path)
        ),
        None,
    )
    ranked = sorted(sites, key=lambda site: _site_rank(site, catalog), reverse=True)
    active = next(
        (site for site in ranked if site.active), ranked[0] if ranked else None
    )
    others = tuple(
        site for site in _others_order(ranked, active) if site is not dest_site
    )
    dest_rank = _destination_rank(destination_path, catalog)
    winner_after_save = None
    for site in ranked:
        if site is dest_site:
            continue
        if _site_rank(site, catalog) > dest_rank:
            winner_after_save = site
            break
    alias_of = catalog.alias_provenance.get(trigger)
    if alias_of == trigger:
        alias_of = None
    if catalog.entry_for(trigger) is not None:
        alias_of = None
    return SnippetRedefinition(
        trigger=trigger,
        destination_path=destination_path,
        destination_site=dest_site,
        active=active,
        others=others,
        winner_after_save=winner_after_save,
        alias_of=alias_of,
    )


def snippet_redefinition_warning(
    redef: SnippetRedefinition,
    destination_display: str,
) -> str | None:
    """Return the shared warning sentence, or ``None`` when nothing to warn."""
    ref = f"⇥ {redef.trigger}"
    dest = destination_display
    dest_site = redef.destination_site
    if dest_site is not None:
        if dest_site.active:
            return None
        winner = dest_site.shadowed_by
        if winner:
            return (
                f"⚠ {ref} in {dest} is shadowed by {winner} — "
                "edits here won't take effect"
            )
        if redef.winner_after_save is not None:
            return (
                f"⚠ {ref} in {dest} is shadowed by "
                f"{redef.winner_after_save.display} — edits here won't take effect"
            )
        return None
    if redef.alias_of:
        return (
            f"⚠ ⇥ {redef.trigger} is an alias of ⇥ {redef.alias_of} — "
            f"saving defines ⇥ {redef.trigger} directly"
        )
    active = redef.active
    if active is None:
        return None
    extra = len(redef.others) - 1
    more = f" (+{extra} more)" if extra > 0 else ""
    if redef.winner_after_save is None:
        return (
            f"⚠ {ref} already exists in {active.display}{more} — "
            f"saving to {dest} will override it"
        )
    return (
        f"⚠ {ref} already exists in {active.display} — a copy in {dest} "
        f"would be shadowed by {redef.winner_after_save.display} and won't take effect"
    )


def snippet_create_verdict(trigger: str, destination_display: str) -> str:
    """Return the success copy for a fresh trigger at *destination_display*."""
    return f"✓ Create ⇥ {trigger} at {destination_display}"


def snippet_edit_in_place_verdict(trigger: str, destination_display: str) -> str:
    """Return the success copy for an in-place edit of the active definition."""
    return f"✓ Edit ⇥ {trigger} in place · {destination_display}"


def shift_tab_edit_suffix(
    redef: SnippetRedefinition,
    locations: Sequence[SnippetConfigLocation],
) -> str:
    """Return the name-step suffix pointing at a writable winner, if any."""
    winner = redef.winner_after_save
    if winner is None or not winner.writable or not winner.path:
        return ""
    location = _location_for_path(winner.path, locations)
    if location is None:
        return ""
    if _path_matches_destination(location.path, redef.destination_path):
        return ""
    return f" · ⇧tab to edit it in {location.label} instead"


def _site_from_contribution(
    contribution: SnippetSourceContribution,
    *,
    active: bool,
    winner_display: str | None,
    writable_paths: frozenset[str] | None,
) -> SnippetDefinitionSite:
    return SnippetDefinitionSite(
        trigger=contribution.trigger,
        kind=contribution.kind,
        path=contribution.path,
        display=_site_display(contribution),
        template=contribution.template,
        writable=_contribution_writable(contribution, writable_paths),
        active=active,
        shadowed_by=None if active else winner_display,
        layer=contribution.layer,
        macro_name=contribution.macro_name,
    )


def _site_display(contribution: SnippetSourceContribution) -> str:
    layer = contribution.layer or ""
    if contribution.kind == "default" or layer == "default":
        return "built-in default_config.yml"
    if contribution.kind == "plugin" or layer.startswith("plugin:"):
        module = layer.removeprefix("plugin:") if layer.startswith("plugin:") else ""
        if not module and contribution.path:
            module = Path(contribution.path).stem
        return f"plugin {module or 'plugin'}"
    if is_macro_derived_kind(contribution.kind):
        name = contribution.macro_name or contribution.trigger
        return f"#{name} (macro snippet)"
    if contribution.display_path:
        return _short_display(contribution.display_path)
    if contribution.path:
        return _short_display(contribution.path)
    return contribution.kind


def _short_display(path: str) -> str:
    home = str(Path.home())
    cwd = str(Path.cwd())
    if path.startswith(cwd + "/"):
        return "./" + path[len(cwd) + 1 :]
    if path.startswith(home + "/"):
        return "~" + path[len(home) :]
    return path


def _same_source(
    contribution: SnippetSourceContribution,
    origin: SnippetSourceContribution,
) -> bool:
    if is_macro_derived_kind(contribution.kind) or is_macro_derived_kind(origin.kind):
        return (
            contribution.kind == origin.kind
            and contribution.macro_name == origin.macro_name
            and contribution.trigger == origin.trigger
        )
    if contribution.layer and origin.layer:
        if contribution.layer == origin.layer:
            if not contribution.path or not origin.path:
                return True
            return paths_equivalent(contribution.path, origin.path)
    if contribution.path and origin.path:
        return paths_equivalent(contribution.path, origin.path)
    return contribution.kind == origin.kind and contribution.template == origin.template


def _contribution_writable(
    contribution: SnippetSourceContribution,
    writable_paths: frozenset[str] | None,
) -> bool:
    if is_macro_derived_kind(contribution.kind) or contribution.kind in {
        "default",
        "plugin",
        "pending",
    }:
        return False
    if not contribution.path:
        return False
    if writable_paths is None:
        return contribution.writable
    return bool(_normalized_paths(contribution.path) & writable_paths)


def _writable_location_paths(
    locations: Sequence[SnippetConfigLocation] | None,
) -> frozenset[str] | None:
    if locations is None:
        return None
    keys: set[str] = set()
    for location in locations:
        if location.disabled_reason is not None:
            continue
        keys.update(_normalized_paths(location.path))
    return frozenset(keys)


def _location_for_path(
    path: str,
    locations: Sequence[SnippetConfigLocation],
) -> SnippetConfigLocation | None:
    for location in locations:
        if paths_equivalent(location.path, path):
            return location
    return None


def _others_order(
    ranked: Sequence[SnippetDefinitionSite],
    active: SnippetDefinitionSite | None,
) -> tuple[SnippetDefinitionSite, ...]:
    if active is None:
        return tuple(ranked)
    rest = [site for site in ranked if site is not active]
    return (active, *rest)


def _site_rank(site: SnippetDefinitionSite, catalog: SnippetCatalog) -> int:
    return _source_rank(
        kind=site.kind,
        layer=site.layer,
        path=site.path,
        layer_names=catalog.layer_names,
        layer_paths=catalog.layer_paths,
    )


def _destination_rank(destination_path: str, catalog: SnippetCatalog) -> int:
    for index, layer_path in enumerate(catalog.layer_paths):
        if layer_path is not None and paths_equivalent(layer_path, destination_path):
            return index
    return _OUT_OF_DISCOVERY_RANK


def _source_rank(
    *,
    kind: str,
    layer: str | None,
    path: str | None,
    layer_names: tuple[str, ...],
    layer_paths: tuple[str | None, ...],
) -> int:
    if is_macro_derived_kind(kind):
        return _MACRO_DERIVED_RANK
    if layer and layer in layer_names:
        return layer_names.index(layer)
    if path:
        for index, layer_path in enumerate(layer_paths):
            if layer_path is not None and paths_equivalent(path, layer_path):
                return index
    if kind in _KIND_FALLBACK_RANK:
        return _KIND_FALLBACK_RANK[kind]
    return 5


def _path_matches_destination(path: str | None, destination_path: str) -> bool:
    if not path:
        return False
    return paths_equivalent(path, destination_path)


def paths_equivalent(left: str | None, right: str | None) -> bool:
    """Return True when *left* and *right* name the same chezmoi-aware file."""
    if not left or not right:
        return False
    if left == right:
        return True
    return bool(_normalized_paths(left) & _normalized_paths(right))


def _normalized_paths(path: str) -> frozenset[str]:
    keys = {path}
    try:
        expanded = str(Path(path).expanduser())
        keys.add(expanded)
    except Exception:
        return frozenset(keys)
    try:
        target = resolve_macro_write_target(path)
    except Exception:
        return frozenset(keys)
    keys.add(str(target.read_path))
    keys.add(str(target.write_path))
    try:
        keys.add(str(target.read_path.expanduser()))
        keys.add(str(target.write_path.expanduser()))
    except Exception:
        pass
    return frozenset(keys)


__all__ = [
    "SnippetDefinitionSite",
    "SnippetRedefinition",
    "paths_equivalent",
    "shift_tab_edit_suffix",
    "snippet_create_verdict",
    "snippet_definition_sites",
    "snippet_edit_in_place_verdict",
    "snippet_redefinition",
    "snippet_redefinition_warning",
]
