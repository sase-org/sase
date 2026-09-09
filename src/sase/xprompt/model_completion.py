"""Completion catalog for ``%model`` directive values.

The Python LLM registry owns model/provider metadata. This module builds the
JSON-serializable catalog shared by the ACE prompt input and the Rust xprompt
LSP launcher materialization. The static catalog deliberately excludes
temporary alias overrides: ACE can apply a cheap live overlay, while the LSP
payload remains a launch-time configuration snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping

from sase.config.core import current_config_token
from sase.llm_provider.alias_view import build_alias_views
from sase.llm_provider.config import (
    BUILTIN_MODEL_ALIAS_NAMES,
    get_model_aliases,
)
from sase.llm_provider.provider_disable import (
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import (
    ProviderRoutingContext,
    resolve_provider_routing_context,
)
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context
from sase.llm_provider.registry import (
    get_llm_metadata_payload,
    model_advisory_marker,
    model_picker_hidden_provider_names,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride
from sase.xprompt._model_completion_catalog import (
    build_static_model_completion_catalog,
)
from sase.xprompt._model_completion_entry import (
    MODEL_COMPLETION_CATALOG_SCHEMA_VERSION,
    MODEL_COMPLETION_ENTRY_WIRE_FIELDS,
    ModelCompletionEntry,
)
from sase.xprompt._model_completion_routing import (
    overlay_live_model_completion_entries,
)
from sase.xprompt._model_completion_wire import (
    filter_model_alias_shortcut_entries,
    filter_model_completion_entries,
    model_completion_entry_to_wire,
    model_completion_entry_wire_rows,
)

# Built-in size aliases surfaced as ``%model`` completions, in display order.
_IMPLICIT_ALIASES: tuple[str, ...] = BUILTIN_MODEL_ALIAS_NAMES

_CatalogCache = tuple[tuple[object, ...], tuple[ModelCompletionEntry, ...]]
_CATALOG_CACHE: _CatalogCache | None = None


def build_model_completion_catalog(
    *,
    use_cache: bool = True,
    overrides: Mapping[str, TemporaryLLMOverride] | None = None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
    routing_context: ProviderRoutingContext | None = None,
) -> list[ModelCompletionEntry]:
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
    return _overlay_live_model_completion_entries(
        entries,
        overrides=overrides,
        provider_disables=provider_disables,
        routing_context=routing_context,
    )


def peek_cached_model_completion_catalog(
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None = None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None = None,
    routing_context: ProviderRoutingContext | None = None,
) -> list[ModelCompletionEntry] | None:
    """Return the warm model catalog without building it on a cache miss."""
    token = current_config_token()
    if _CATALOG_CACHE is None or _CATALOG_CACHE[0] != token:
        return None
    return _overlay_live_model_completion_entries(
        list(_CATALOG_CACHE[1]),
        overrides=overrides,
        provider_disables=provider_disables,
        routing_context=routing_context,
    )


def model_completion_catalog_payload() -> dict[str, object]:
    """Return the launch-time JSON snapshot materialized for the Rust LSP."""
    context = resolve_provider_routing_context()
    return {
        "schema_version": MODEL_COMPLETION_CATALOG_SCHEMA_VERSION,
        "entries": [
            model_completion_entry_to_wire(entry)
            for entry in build_model_completion_catalog(
                overrides={},
                routing_context=context,
            )
        ],
    }


def _build_static_catalog() -> list[ModelCompletionEntry]:
    payload = get_llm_metadata_payload()
    hidden_providers = model_picker_hidden_provider_names()
    try:
        alias_views = {
            view.name: view
            for view in build_alias_views(overrides={}, provider_disables={})
        }
    except Exception:  # noqa: BLE001 - plain aliases are the safe fallback.
        alias_views = {}

    return build_static_model_completion_catalog(
        metadata_payload=payload,
        user_aliases=get_model_aliases(),
        alias_views=alias_views,
        hidden_providers=hidden_providers,
        implicit_aliases=_IMPLICIT_ALIASES,
        advisory_marker=model_advisory_marker,
    )


def _overlay_live_model_completion_entries(
    entries: list[ModelCompletionEntry],
    *,
    overrides: Mapping[str, TemporaryLLMOverride] | None,
    provider_disables: Mapping[str, TemporaryProviderDisable] | None,
    routing_context: ProviderRoutingContext | None,
) -> list[ModelCompletionEntry]:
    """Apply live provider and temporary-alias overlays to a static catalog."""
    return overlay_live_model_completion_entries(
        entries,
        overrides=overrides,
        provider_disables=provider_disables,
        routing_context=routing_context,
        build_alias_views_func=build_alias_views,
        peek_provider_routing_context_func=peek_provider_routing_context,
        resolve_provider_routing_context_func=resolve_provider_routing_context,
    )


__all__ = [
    "MODEL_COMPLETION_CATALOG_SCHEMA_VERSION",
    "MODEL_COMPLETION_ENTRY_WIRE_FIELDS",
    "ModelCompletionEntry",
    "build_model_completion_catalog",
    "filter_model_alias_shortcut_entries",
    "filter_model_completion_entries",
    "model_completion_entry_wire_rows",
    "model_completion_catalog_payload",
    "peek_cached_model_completion_catalog",
]
