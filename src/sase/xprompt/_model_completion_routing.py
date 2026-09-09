"""Live routing and temporary override overlays for ``%model`` completions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from sase.llm_provider.alias_view import AliasView
from sase.llm_provider.load_balancing import MemberAvailability
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_priority import (
    ProviderAvailability,
    ProviderRoutingContext,
    classify_provider_availability,
    provider_availability_facts,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.xprompt._model_completion_entry import ModelCompletionEntry

BuildAliasViews = Callable[..., Sequence[AliasView]]
PeekProviderRoutingContext = Callable[[], ProviderRoutingContext]
ResolveProviderRoutingContext = Callable[..., ProviderRoutingContext]


def overlay_live_model_completion_entries(
    entries: list[ModelCompletionEntry],
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None,
    routing_context: ProviderRoutingContext | None,
    build_alias_views_func: BuildAliasViews,
    peek_provider_routing_context_func: PeekProviderRoutingContext,
    resolve_provider_routing_context_func: ResolveProviderRoutingContext,
) -> list[ModelCompletionEntry]:
    """Apply live provider and temporary-alias overlays to a static catalog."""
    if routing_context is not None and provider_disables is not None:
        raise ValueError("pass routing_context or provider_disables, not both")
    context = (
        peek_provider_routing_context_func()
        if routing_context is None and provider_disables is None
        else resolve_provider_routing_context_func(
            routing_context=routing_context,
            provider_disables=provider_disables,
        )
    )
    if context.provider_disables or context.priority is not None:
        return _apply_provider_routing(
            entries,
            context,
            overrides=overrides,
            build_alias_views_func=build_alias_views_func,
        )
    if overrides is not None:
        return _apply_alias_overrides(entries, overrides)
    return entries


def _apply_alias_overrides(
    entries: list[ModelCompletionEntry],
    overrides: Mapping[str, TemporaryLLMOverride],
) -> list[ModelCompletionEntry]:
    """Return *entries* with temporary targets overlaid on matching aliases."""
    if not overrides:
        return list(entries)

    positions = {
        entry.value.lstrip("@"): index
        for index, entry in enumerate(entries)
        if entry.kind in {"implicit_alias", "user_alias"}
    }
    overlaid = list(entries)
    for raw_alias, override in overrides.items():
        index = positions.get(raw_alias.lstrip("@"))
        if index is None:
            continue
        overlaid[index] = replace(
            overlaid[index],
            target_provider=override.provider,
            target_model=override.model,
            target_effort=override.effort or "",
            provenance="override",
            reference="",
            reference_effort="",
            selector_mode="",
            pool_available=0,
            pool_total=0,
        )

    return overlaid


def _apply_provider_routing(
    entries: list[ModelCompletionEntry],
    routing_context: ProviderRoutingContext,
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None,
    build_alias_views_func: BuildAliasViews,
) -> list[ModelCompletionEntry]:
    """Drop unavailable concrete entries and refresh alias target metadata."""
    filtered: list[ModelCompletionEntry] = []
    for entry in entries:
        if entry.kind not in {"model", "provider"}:
            filtered.append(entry)
            continue
        routing = _completion_provider_routing(entry.provider, routing_context)
        if routing.availability == MemberAvailability.UNAVAILABLE:
            continue
        filtered.append(replace(entry, provenance=_completion_provenance(routing)))
    try:
        alias_views = {
            view.name: view
            for view in build_alias_views_func(
                overrides=overrides or {},
                routing_context=routing_context,
            )
        }
    except Exception:  # noqa: BLE001 - keep concrete filtering if aliases fail.
        return _apply_alias_overrides(filtered, overrides or {})

    overlaid: list[ModelCompletionEntry] = []
    for entry in filtered:
        if entry.kind not in {"implicit_alias", "user_alias"}:
            overlaid.append(entry)
            continue
        view = alias_views.get(entry.value.lstrip("@"))
        if view is None:
            overlaid.append(entry)
            continue
        selector_members = tuple(
            member for member in view.selector_members if not member.last_resort
        )
        provenance = "configured" if view.configured else "implicit"
        if view.override is not None:
            provenance = "override_paused" if view.is_override_paused else "override"
        elif "actual_soft_disable" in view.provenance:
            provenance = "soft"
        elif "priority" in view.provenance:
            provenance = "priority"
        elif "priority_backup" in view.provenance:
            provenance = "backup"
        overlaid.append(
            replace(
                entry,
                target_provider=view.provider or "",
                target_model=view.model,
                target_effort=view.effort or "",
                provenance=provenance,
                reference=view.references or view.implicit_fallback or "",
                reference_effort=view.reference_effort or "",
                selector_mode=view.selector_mode or "",
                pool_available=sum(member.available for member in selector_members),
                pool_total=len(selector_members),
                config_source=view.configured_source or "",
                bucket=view.bucket or "",
            )
        )
    return overlaid


def _completion_provider_routing(
    provider: str,
    routing_context: ProviderRoutingContext,
) -> ProviderAvailability:
    """Classify a catalog provider without folding in CLI availability."""
    return classify_provider_availability(
        routing_context,
        provider_availability_facts(
            provider,
            registered=True,
            user_facing=True,
            cli_available=True,
        ),
    )


def _completion_provenance(routing: ProviderAvailability) -> str:
    """Return the compact completion label for provider routing provenance."""
    provenance = routing.provenance
    if "actual_soft_disable" in provenance:
        return "soft"
    if "priority" in provenance:
        return "priority"
    if "priority_backup" in provenance:
        return "backup"
    return ""


__all__ = ["overlay_live_model_completion_entries"]
