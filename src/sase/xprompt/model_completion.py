"""Completion catalog for ``%model`` directive values.

The Python LLM registry owns model/provider metadata. This module builds the
JSON-serializable catalog shared by the ACE prompt input and the Rust xprompt
LSP launcher materialization. The static catalog deliberately excludes
temporary alias overrides: ACE can apply a cheap live overlay, while the LSP
payload remains a launch-time configuration snapshot.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from sase.config.core import current_config_token
from sase.llm_provider.alias_view import AliasView, build_alias_views

from sase.llm_provider.config import (
    BUILTIN_MODEL_ALIAS_NAMES,
    get_model_aliases,
)
from sase.llm_provider.registry import (
    get_llm_metadata_payload,
    model_advisory_marker,
    model_picker_hidden_provider_names,
)
from sase.llm_provider.provider_disable import (
    TemporaryProviderDisable,
    get_active_provider_disables,
)
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables
from sase.llm_provider.temporary_override import TemporaryLLMOverride

#: Wire schema understood by existing Rust LSP versions. Alias metadata is
#: additive under v1 so old readers ignore it and new readers can still load
#: stale v1 catalogs that omit it.
MODEL_COMPLETION_CATALOG_SCHEMA_VERSION = 1

_INLINE_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-=./@]+$")

# Built-in size aliases surfaced as ``%model`` completions, in display order.
_IMPLICIT_ALIASES: tuple[str, ...] = BUILTIN_MODEL_ALIAS_NAMES


@dataclass(frozen=True, slots=True)
class _ModelCompletionEntry:
    """One inline-completable ``%model`` value."""

    value: str
    display: str
    description: str = ""
    kind: str = "model"
    provider: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    alias_kind: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    provenance: str = ""
    reference: str = ""
    reference_effort: str = ""
    selector_mode: str = ""
    pool_available: int = 0
    pool_total: int = 0
    config_source: str = ""
    bucket: str = ""
    advisory_label: str = ""
    advisory_severity: str = ""
    provider_model_count: int = 0


_CatalogCache = tuple[tuple[object, ...], tuple[_ModelCompletionEntry, ...]]
_CATALOG_CACHE: _CatalogCache | None = None


def build_model_completion_catalog(
    *,
    use_cache: bool = True,
    overrides: Mapping[str, TemporaryLLMOverride] | None = None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
) -> list[_ModelCompletionEntry]:
    """Return ordered inline-completable ``%model`` values.

    Canonical model names come from the cached LLM metadata payload. Short
    aliases are kept as match/display hints only; they are not inserted as
    completion values. The five implicit size aliases and user-configured
    aliases are inserted with their ``@`` form because those values resolve
    through the normal ``%model`` path.
    """
    global _CATALOG_CACHE  # noqa: PLW0603

    token = current_config_token() if use_cache else None
    if use_cache and _CATALOG_CACHE is not None and _CATALOG_CACHE[0] == token:
        entries = list(_CATALOG_CACHE[1])
    else:
        entries = _build_static_catalog()
        if use_cache:
            assert token is not None
            _CATALOG_CACHE = (token, tuple(entries))
    disables = (
        peek_active_provider_disables()
        if provider_disables is None
        else provider_disables
    )
    if disables:
        entries = _apply_provider_disables(entries, disables, overrides=overrides)
    elif overrides is not None:
        entries = _apply_alias_overrides(entries, overrides)
    if overrides is None and not disables:
        return entries
    return entries


def model_completion_catalog_payload() -> dict[str, object]:
    """Return the launch-time JSON snapshot materialized for the Rust LSP."""
    provider_disables = get_active_provider_disables()
    return {
        "schema_version": MODEL_COMPLETION_CATALOG_SCHEMA_VERSION,
        "entries": [
            {
                "value": entry.value,
                "display": entry.display,
                "description": entry.description,
                "kind": entry.kind,
                "provider": entry.provider,
                "aliases": list(entry.aliases),
                "alias_kind": entry.alias_kind,
                "target_provider": entry.target_provider,
                "target_model": entry.target_model,
                "target_effort": entry.target_effort,
                "provenance": entry.provenance,
                "reference": entry.reference,
                "reference_effort": entry.reference_effort,
                "selector_mode": entry.selector_mode,
                "pool_available": entry.pool_available,
                "pool_total": entry.pool_total,
                "config_source": entry.config_source,
                "bucket": entry.bucket,
                "advisory_label": entry.advisory_label,
                "advisory_severity": entry.advisory_severity,
                "provider_model_count": entry.provider_model_count,
            }
            for entry in build_model_completion_catalog(
                overrides={},
                provider_disables=provider_disables,
            )
        ],
    }


def filter_model_completion_entries(
    entries: list[_ModelCompletionEntry],
    partial: str,
) -> list[_ModelCompletionEntry]:
    """Return entries whose value or alias hint prefix-matches ``partial``.

    A leading ``@`` is an explicit alias-only gate. Bare partials retain the
    established behavior where alias hints match without ``@`` while catalog
    order keeps concrete models before aliases.
    """
    needle = partial.lower()
    if not needle:
        return list(entries)
    if needle.startswith("@"):
        return [
            entry
            for entry in entries
            if entry.kind in {"implicit_alias", "user_alias"}
            and (
                entry.value.lower().startswith(needle)
                or any(
                    f"@{alias.lstrip('@')}".lower().startswith(needle)
                    for alias in entry.aliases
                )
            )
        ]
    if scope := _provider_scope(entries, needle):
        provider, remainder = scope
        return [
            _qualified_entry(entry, provider)
            for entry in entries
            if entry.kind == "model"
            and entry.provider.casefold() == provider.casefold()
            and (
                entry.value.lower().startswith(remainder)
                or any(alias.lower().startswith(remainder) for alias in entry.aliases)
            )
        ]
    return [
        entry
        for entry in entries
        if entry.value.lower().startswith(needle)
        or any(alias.lower().startswith(needle) for alias in entry.aliases)
    ]


def _apply_alias_overrides(
    entries: list[_ModelCompletionEntry],
    overrides: Mapping[str, TemporaryLLMOverride],
) -> list[_ModelCompletionEntry]:
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


def _apply_provider_disables(
    entries: list[_ModelCompletionEntry],
    disables: Mapping[str, TemporaryProviderDisable],
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None,
) -> list[_ModelCompletionEntry]:
    """Drop disabled concrete entries and refresh alias target metadata."""
    disabled_providers = set(disables)
    filtered = [
        entry
        for entry in entries
        if not (
            entry.provider in disabled_providers and entry.kind in {"model", "provider"}
        )
    ]
    try:
        alias_views = {
            view.name: view
            for view in build_alias_views(
                overrides=overrides or {},
                provider_disables=disables,
            )
        }
    except Exception:  # noqa: BLE001 - keep concrete filtering if aliases fail.
        return _apply_alias_overrides(filtered, overrides or {})

    overlaid: list[_ModelCompletionEntry] = []
    for entry in filtered:
        if entry.kind not in {"implicit_alias", "user_alias"}:
            overlaid.append(entry)
            continue
        view = alias_views.get(entry.value.lstrip("@"))
        if view is None:
            overlaid.append(entry)
            continue
        selector_members = view.selector_members
        provenance = "configured" if view.configured else "implicit"
        if view.override is not None:
            provenance = "override_paused" if view.is_override_paused else "override"
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


def _build_static_catalog() -> list[_ModelCompletionEntry]:
    payload = get_llm_metadata_payload()
    providers = _dict(payload.get("providers"))
    model_to_provider = _str_dict(payload.get("model_to_provider"))
    short_aliases = _str_dict(payload.get("model_short_aliases"))
    advisories = _advisory_labels(payload.get("model_advisories"))
    hidden_providers = model_picker_hidden_provider_names()
    provider_order = [
        provider
        for provider in _provider_order(payload, providers)
        if provider not in hidden_providers
    ]
    try:
        alias_views = {
            view.name: view
            for view in build_alias_views(overrides={}, provider_disables={})
        }
    except Exception:  # noqa: BLE001 - plain aliases are the safe fallback.
        alias_views = {}

    entries: list[_ModelCompletionEntry] = []
    seen: set[str] = set()
    contributing_providers: dict[str, tuple[str, int]] = {}
    for provider in provider_order:
        provider_metadata = _dict(providers.get(provider))
        known_models = _str_list(provider_metadata.get("known_model_names"))
        provider_display = _provider_display(provider, provider_metadata)
        for model in known_models:
            if model_to_provider.get(model) != provider:
                continue
            if _append_model_entry(
                entries,
                seen,
                model=model,
                provider=provider,
                provider_display=provider_display,
                short_alias=short_aliases.get(model, ""),
                advisory=advisories.get(model, ("", "")),
            ):
                _, count = contributing_providers.get(provider, (provider_display, 0))
                contributing_providers[provider] = (provider_display, count + 1)

    # Include any model_to_provider entries missing from provider metadata so
    # the catalog follows the actual resolution map even if plugin metadata is
    # partial.
    for model, provider in sorted(model_to_provider.items()):
        if model in seen or provider in hidden_providers:
            continue
        provider_metadata = _dict(providers.get(provider))
        provider_display = _provider_display(provider, provider_metadata)
        if _append_model_entry(
            entries,
            seen,
            model=model,
            provider=provider,
            provider_display=provider_display,
            short_alias=short_aliases.get(model, ""),
            advisory=advisories.get(model, ("", "")),
        ):
            _, count = contributing_providers.get(provider, (provider_display, 0))
            contributing_providers[provider] = (provider_display, count + 1)

    user_aliases = get_model_aliases()
    _append_implicit_alias_entries(
        entries,
        seen,
        user_aliases=user_aliases,
        alias_views=alias_views,
    )

    for alias in sorted(user_aliases):
        if alias in seen:
            continue
        _append_alias_entry(
            entries,
            seen,
            value=alias,
            view=alias_views.get(alias),
            kind="user_alias",
        )

    provider_row_order = [
        *provider_order,
        *sorted(
            provider
            for provider in contributing_providers
            if provider not in provider_order
        ),
    ]
    for provider in provider_row_order:
        provider_contribution = contributing_providers.get(provider)
        if provider_contribution is None:
            continue
        provider_display, model_count = provider_contribution
        _append_provider_entry(
            entries,
            seen,
            provider=provider,
            provider_display=provider_display,
            model_count=model_count,
        )

    return entries


def _provider_scope(
    entries: list[_ModelCompletionEntry],
    needle: str,
) -> tuple[str, str] | None:
    head, separator, remainder = needle.partition("/")
    if not separator or not head:
        return None
    provider_entry = next(
        (
            entry
            for entry in entries
            if entry.kind == "provider" and entry.value.casefold() == f"{head}/"
        ),
        None,
    )
    if provider_entry is None:
        return None
    return provider_entry.provider or head, remainder


def _qualified_entry(
    entry: _ModelCompletionEntry,
    provider: str,
) -> _ModelCompletionEntry:
    prefix = f"{provider}/"
    return replace(
        entry,
        value=f"{prefix}{entry.value}",
        display=f"{prefix}{entry.display}",
    )


def _append_implicit_alias_entries(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    user_aliases: dict[str, str],
    alias_views: dict[str, AliasView],
) -> None:
    """Append the implicit built-in size aliases.

    An implicit alias the user has shadowed via ``model_aliases`` is skipped here
    so the user-configured target is surfaced once, with its real
    description, by the caller's user-alias loop.
    """
    for value in _IMPLICIT_ALIASES:
        if value in user_aliases:
            continue
        view = alias_views.get(value)
        _append_alias_entry(
            entries,
            seen,
            value=value,
            view=view,
            kind="implicit_alias",
        )


def _append_model_entry(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    model: str,
    provider: str,
    provider_display: str,
    short_alias: str,
    advisory: tuple[str, str] = ("", ""),
) -> bool:
    if model in seen or not _is_inline_completable(model):
        return False
    aliases = (short_alias,) if short_alias else ()
    description = provider_display
    if short_alias:
        description = f"{provider_display} ({short_alias})"
    advisory_label, advisory_severity = advisory
    if advisory_label:
        # The completion detail is the only thing a user sees while typing
        # `%model:...`, so the advisory has to ride along with it.
        glyph = model_advisory_marker(advisory_severity)
        description = f"{description} — {glyph} {advisory_label}"
    entries.append(
        _ModelCompletionEntry(
            value=model,
            display=model,
            description=description,
            kind="model",
            provider=provider,
            aliases=aliases,
            advisory_label=advisory_label,
            advisory_severity=advisory_severity if advisory_label else "",
        )
    )
    seen.add(model)
    return True


def _append_provider_entry(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    provider: str,
    provider_display: str,
    model_count: int,
) -> None:
    value = f"{provider}/"
    if value in seen or not _is_inline_completable(value):
        return
    entries.append(
        _ModelCompletionEntry(
            value=value,
            display=value,
            description=provider_display,
            kind="provider",
            provider=provider,
            provider_model_count=model_count,
        )
    )
    seen.add(value)


def _advisory_labels(value: object) -> dict[str, tuple[str, str]]:
    """Return ``{model → (label, severity)}`` from the registry payload."""
    labels: dict[str, tuple[str, str]] = {}
    for model, advisory in _dict(value).items():
        entry = _str_dict(advisory)
        if label := entry.get("label", ""):
            labels[model] = (label, entry.get("severity", ""))
    return labels


def _append_alias_entry(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    value: str,
    view: AliasView | None,
    kind: str,
    description: str = "",
) -> None:
    display_value = f"@{value}" if not value.startswith("@") else value
    bare_alias = display_value[1:] if display_value.startswith("@") else display_value
    if display_value in seen or not _is_inline_completable(display_value):
        return
    if view is not None:
        description = description or view.description or ""
        reference = view.references or view.implicit_fallback or ""
        selector_members = view.selector_members
        entry = _ModelCompletionEntry(
            value=display_value,
            display=display_value,
            description=description,
            kind=kind,
            provider="",
            aliases=(bare_alias,),
            alias_kind=view.kind,
            target_provider=view.provider or "",
            target_model=view.model,
            target_effort=view.effort or "",
            provenance="configured" if view.configured else "implicit",
            reference=reference,
            reference_effort=view.reference_effort or "",
            selector_mode=view.selector_mode or "",
            pool_available=sum(member.available for member in selector_members),
            pool_total=len(selector_members),
            config_source=view.configured_source or "",
            bucket=view.bucket or "",
        )
    else:
        entry = _ModelCompletionEntry(
            value=display_value,
            display=display_value,
            description=description,
            kind=kind,
            provider="",
            aliases=(bare_alias,),
        )
    entries.append(entry)
    seen.add(display_value)


def _provider_order(
    payload: dict[str, object],
    providers: dict[str, object],
) -> list[str]:
    ordered: list[str] = []
    for item in _dict_list(payload.get("autodetect_candidates")):
        provider = item.get("provider")
        if (
            isinstance(provider, str)
            and provider in providers
            and provider not in ordered
        ):
            ordered.append(provider)
    ordered.extend(
        sorted(provider for provider in providers if provider not in ordered)
    )
    return ordered


def _provider_display(provider: str, metadata: dict[str, object]) -> str:
    for key in ("display_name", "provider_name"):
        provider_name = metadata.get(key)
        if isinstance(provider_name, str) and provider_name:
            return provider_name
    return provider


def _is_inline_completable(value: str) -> bool:
    return _INLINE_MODEL_VALUE_RE.fullmatch(value) is not None


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


__all__ = [
    "MODEL_COMPLETION_CATALOG_SCHEMA_VERSION",
    "build_model_completion_catalog",
    "filter_model_completion_entries",
    "model_completion_catalog_payload",
]
