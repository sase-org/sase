"""Pure analysis for the snippet trigger-name panel."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sase.macro.naming import validate_snippet_trigger
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
from sase.snippet.models import SnippetCatalog, is_macro_derived_kind
from sase.snippet.redefinition import (
    SnippetDefinitionSite,
    SnippetRedefinition,
    shift_tab_edit_suffix,
    snippet_create_verdict,
    snippet_definition_sites,
    snippet_edit_in_place_verdict,
    snippet_redefinition,
    snippet_redefinition_warning,
)

_PREFIX_MATCH_LIMIT = 6
_PREVIEW_MAX_CHARS = 52


@dataclass(frozen=True, slots=True)
class SnippetMatchPreview:
    """One prefix-match row in the name panel."""

    trigger: str
    location_path: str | None
    display_path: str
    body_preview: str
    is_destination: bool = False
    derived_from: str | None = None


@dataclass(frozen=True, slots=True)
class SnippetNameAnalysis:
    """Cached analysis keyed by typed trigger and destination path."""

    trigger: str
    destination_path: str
    redefinition: SnippetRedefinition
    destination_exists: bool
    matches: tuple[SnippetMatchPreview, ...]
    verdict_kind: str
    verdict: str
    save_warning: str | None

    @property
    def has_collision(self) -> bool:
        redef = self.redefinition
        return self.destination_exists or bool(
            redef.active or redef.alias_of or redef.others
        )


def build_snippet_name_analysis(
    trigger: str,
    target: SnippetSaveTarget,
    locations: Sequence[SnippetConfigLocation],
    catalog: SnippetCatalog,
) -> SnippetNameAnalysis:
    """Build the live name-step analysis from an already-loaded catalog."""
    destination_path = str(target.write_path)
    redef = snippet_redefinition(
        catalog,
        trigger,
        destination_path,
        locations=locations,
    )
    matches = prefix_matches(trigger, destination_path, catalog, locations)
    verdict_kind, verdict, save_warning = _verdict_for(
        trigger,
        target,
        locations,
        redef,
    )
    return SnippetNameAnalysis(
        trigger=trigger,
        destination_path=destination_path,
        redefinition=redef,
        destination_exists=redef.destination_site is not None,
        matches=matches,
        verdict_kind=verdict_kind,
        verdict=verdict,
        save_warning=save_warning,
    )


def existing_body_for(redef: SnippetRedefinition) -> str | None:
    """Return the in-memory template the name step should load."""
    if redef.destination_site is not None:
        return redef.destination_site.template
    if redef.active is not None:
        return redef.active.template
    if redef.alias_of:
        return None
    return None


def derived_from_for(redef: SnippetRedefinition) -> str | None:
    """Return the macro origin label when the active definition is macro-derived."""
    active = redef.active
    if active is None or not is_macro_derived_kind(active.kind):
        return None
    name = active.macro_name or active.trigger
    return f"#{name}"


def prefix_matches(
    trigger: str,
    destination_path: str,
    catalog: SnippetCatalog,
    locations: Sequence[SnippetConfigLocation],
) -> tuple[SnippetMatchPreview, ...]:
    """Return prefix matches from catalog sites without reading files."""
    del locations
    if not trigger:
        return ()
    matches: list[tuple[tuple[object, ...], SnippetMatchPreview]] = []
    seen: set[tuple[str, str | None]] = set()
    for site in snippet_definition_sites(catalog):
        if not site.trigger.startswith(trigger):
            continue
        key = (site.trigger, site.path)
        if key in seen:
            continue
        seen.add(key)
        preview = _preview_from_site(site, destination_path)
        matches.append((_match_sort_key(preview, trigger, site), preview))
    for alias, source in catalog.alias_provenance.items():
        if not alias.startswith(trigger):
            continue
        key = (alias, None)
        if key in seen or catalog.entry_for(alias) is not None:
            continue
        seen.add(key)
        preview = SnippetMatchPreview(
            trigger=alias,
            location_path=None,
            display_path=f"alias of ⇥ {source}",
            body_preview="",
            derived_from=f"⇥ {source}",
        )
        matches.append((_match_sort_key(preview, trigger, None), preview))
    matches.sort(key=lambda item: item[0])
    return tuple(preview for _, preview in matches[:_PREFIX_MATCH_LIMIT])


def _preview_from_site(
    site: SnippetDefinitionSite,
    destination_path: str,
) -> SnippetMatchPreview:
    derived = None
    if is_macro_derived_kind(site.kind):
        name = site.macro_name or site.trigger
        derived = f"#{name}"
    from sase.snippet.redefinition import paths_equivalent

    is_destination = bool(site.path) and paths_equivalent(site.path, destination_path)
    return SnippetMatchPreview(
        trigger=site.trigger,
        location_path=site.path,
        display_path=site.display,
        body_preview=_single_line(site.template),
        is_destination=is_destination,
        derived_from=derived,
    )


def _match_sort_key(
    preview: SnippetMatchPreview,
    trigger: str,
    site: SnippetDefinitionSite | None,
) -> tuple[object, ...]:
    derived_rank = 1 if preview.derived_from else 0
    kind_rank = 0
    if site is not None and is_macro_derived_kind(site.kind):
        kind_rank = 1
    return (
        preview.trigger != trigger,
        preview.trigger.casefold(),
        kind_rank,
        derived_rank,
        preview.display_path,
    )


def _verdict_for(
    trigger: str,
    target: SnippetSaveTarget,
    locations: Sequence[SnippetConfigLocation],
    redef: SnippetRedefinition,
) -> tuple[str, str, str | None]:
    error = validate_snippet_trigger(trigger)
    if error is not None:
        return "error", f"✗ Invalid trigger: {error}", None
    disabled = _disabled_reason(str(target.write_path), locations)
    if disabled is not None:
        return "error", f"✗ {disabled}", None
    dest = target.display_path
    warning = snippet_redefinition_warning(redef, dest)
    suffix = shift_tab_edit_suffix(redef, locations) if warning else ""
    if redef.destination_site is not None and redef.destination_site.active:
        return "success", snippet_edit_in_place_verdict(trigger, dest), None
    if warning:
        return "warning", warning + suffix, warning
    return "success", snippet_create_verdict(trigger, dest), None


def _disabled_reason(
    path: str,
    locations: Sequence[SnippetConfigLocation],
) -> str | None:
    from sase.snippet.redefinition import paths_equivalent

    for location in locations:
        if paths_equivalent(location.path, path) or location.path == path:
            return location.disabled_reason
    return None


def _single_line(value: str, *, max_chars: int = _PREVIEW_MAX_CHARS) -> str:
    line = " ".join(value.split())
    if len(line) <= max_chars:
        return line
    return line[: max_chars - 1] + "…"


__all__ = [
    "SnippetMatchPreview",
    "SnippetNameAnalysis",
    "build_snippet_name_analysis",
    "derived_from_for",
    "existing_body_for",
    "prefix_matches",
]
