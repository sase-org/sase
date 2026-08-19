"""Provider registry for LLM backends.

Providers are discovered by :mod:`sase.llm_provider._registry_plugins` via
``importlib.metadata.entry_points(group="sase_llm")``. Metadata normalization
and cache fingerprints live in :mod:`sase.llm_provider._registry_metadata`,
while catalog assembly lives in :mod:`sase.llm_provider._registry_catalog`.
This module remains the stable façade for registry access and model resolution;
routing state and diagnostics live in :mod:`sase.llm_provider._registry_routing`.

Dispatch uses a single-plugin :class:`pluggy.PluginManager` so only the
selected provider's ``llm_invoke`` hook fires.  Metadata lookups (known
model names, skill deploy paths, auto-detection, retry defaults, ...)
share a memoized multi-plugin PM built by :func:`_build_llm_pm`, and
callers iterate ``pm.list_name_plugin()`` to collect per-plugin values.
"""

import functools
import os
import shutil
from collections.abc import Mapping
from typing import Any

import pluggy

from ._registry_catalog import (
    build_llm_metadata_payload as _build_llm_metadata_payload,
    hidden_provider_names as _hidden_provider_names,
    model_advisory_color,
    model_advisory_map as _model_advisory_map,
    model_advisory_marker,
    provider_interactive_cli_map as _interactive_cli_map_from_payload,
    provider_names as _payload_provider_names,
    provider_vendor_map as _vendor_map_from_payload,
    string_map as _string_map,
)
from ._registry_metadata import (
    llm_metadata_cache_policy,
    provider_metadata,
    provider_path_env_var,
)
from ._registry_plugins import (
    build_llm_plugin_manager,
    create_provider,
)
from ._registry_routing import (
    ProviderDisableSnapshot,
    ProviderRoutingStatus,
    ProviderTemporarilyDisabledError,
    affected_aliases_by_provider as _affected_aliases_by_provider,
    format_provider_disable_expiry,
    format_provider_model_label,
    provider_cli_available as _provider_cli_available_from_payload,
    provider_model_counts as _provider_model_counts_from_payload,
)
from .base import LLMProvider
from .config import (
    get_llm_provider_config,
    resolve_model_alias_with_effort,
)
from .provider_disable import TemporaryProviderDisable, get_active_provider_disables
from .types import ModelTier

LLM_EXEC_PROVIDER_ENV = "SASE_LLM_EXEC_PROVIDER"


@functools.cache
def _build_llm_pm() -> pluggy.PluginManager:
    """Return a shared plugin manager containing every ``sase_llm`` plugin.

    Memoized for the process lifetime: entry-point discovery is walked
    exactly once. Tests that mock entry points must clear the cache via
    ``_build_llm_pm.cache_clear()``.
    """
    return build_llm_plugin_manager()


def iter_plugins() -> list[tuple[str, object]]:
    """Return registered ``(provider_name, plugin_instance)`` pairs."""
    return list(_build_llm_pm().list_name_plugin())


def _llm_metadata_cache_policy() -> dict[str, Any]:
    """Compatibility wrapper for the extracted cache policy builder."""
    return llm_metadata_cache_policy()


def _provider_metadata(name: str, plugin: object) -> dict[str, Any]:
    """Compatibility wrapper for extracted provider metadata normalization."""
    return provider_metadata(name, plugin)


def _direct_llm_metadata_payload() -> dict[str, Any]:
    """Collect LLM metadata directly from pluggy providers inside the host."""
    return _build_llm_metadata_payload(
        iter_plugins(),
        _provider_metadata,
        _llm_metadata_cache_policy(),
    )


@functools.cache
def _llm_metadata_payload() -> dict[str, Any]:
    """Return LLM metadata, memoized for the process lifetime.

    Matches the :func:`_build_llm_pm` pattern: entry-point discovery and
    per-plugin metadata collection happen once. Tests that monkeypatch
    entry points must clear both caches via
    ``_build_llm_pm.cache_clear()`` and ``_llm_metadata_payload.cache_clear()``.
    """
    return _direct_llm_metadata_payload()


def get_llm_metadata_payload() -> dict[str, Any]:
    """Return cached LLM provider metadata for diagnostics and UI callers."""
    return _llm_metadata_payload()


def model_to_provider_map() -> dict[str, str]:
    """Build a ``{model_name → provider_name}`` map from plugin metadata."""
    return _string_map(_llm_metadata_payload(), "model_to_provider")


def provider_short_name_map() -> dict[str, str]:
    """Return ``{provider_name → short_label}`` for agent-name suffixes.

    When a plugin doesn't implement ``llm_provider_short_name``, the
    fallback is its entry-point name — preserving today's behavior for
    plugins that haven't been updated.
    """
    return _string_map(_llm_metadata_payload(), "provider_short_names")


def model_short_alias_map() -> dict[str, str]:
    """Build a ``{model_name → short_alias}`` map from plugin metadata.

    Each provider plugin may declare an ``llm_model_short_aliases`` hook
    returning a dict of long-form model names to short aliases used in
    multi-model agent name suffixes.  Last writer wins on duplicates.
    """
    return _string_map(_llm_metadata_payload(), "model_short_aliases")


def model_advisory_map() -> dict[str, dict[str, str]]:
    """Build a ``{model_name → advisory}`` map from plugin metadata.

    Each advisory is ``{"severity", "label", "detail"}``, already normalized by
    :func:`~sase.llm_provider._registry_metadata.provider_metadata`. Providers
    that declare no ``llm_model_advisories`` hook contribute nothing, so the
    map is empty on a stock install with no advisory-flagged models.
    """
    return _model_advisory_map(_llm_metadata_payload())


def model_advisory_for(model: str | None) -> dict[str, str] | None:
    """Return the advisory for *model*, or ``None`` when it carries none."""
    if not model:
        return None
    return model_advisory_map().get(model)


def provider_cli_status_color_map() -> dict[str, str]:
    """Return provider colors from plugin metadata, plus vendor-family defaults."""
    return _string_map(_llm_metadata_payload(), "provider_cli_status_colors")


def provider_interactive_cli_map() -> dict[str, dict[str, Any]]:
    """Return ``{provider_name → interactive CLI descriptor}`` from metadata.

    Each descriptor is the normalized ``llm_interactive_cli`` payload. Providers
    that omit the hook still appear, with ``argv`` defaulting to the
    autodetected CLI name and ``supported`` defaulting to ``True``.
    """
    return _interactive_cli_map_from_payload(_llm_metadata_payload())


def provider_vendor_map() -> dict[str, str]:
    """Return ``{provider_name → vendor}`` from install metadata.

    Providers that omit ``vendor`` appear with an empty string so callers can
    render the secondary menu label without a second payload walk.
    """
    return _vendor_map_from_payload(_llm_metadata_payload())


def model_picker_hidden_provider_names() -> frozenset[str]:
    """Return provider names flagged as hidden from user-facing model pickers.

    Driven by the ``llm_hidden_from_model_pickers`` plugin hook rather than a
    hardcoded provider name, so any provider (built-in or third-party) that
    exists only for testing can opt out of the ACE model picker and ``%model``
    completion catalog while remaining fully registered and routable.
    """
    return _hidden_provider_names(_llm_metadata_payload())


def _provider_names() -> list[str]:
    """Return all registered provider names (entry-point keys)."""
    return _payload_provider_names(_llm_metadata_payload())


def registered_provider_names() -> list[str]:
    """Return all registered LLM provider names (entry-point keys).

    Public adapter over :func:`_provider_names` for callers outside the
    registry (e.g. the model alias policy in :mod:`sase.llm_provider.config`)
    that need the set of providers without reaching into private helpers.
    """
    return _provider_names()


@functools.cache
def _provider_cli_available(provider_name: str) -> bool:
    """Return whether a registered provider's declared CLI is installed.

    The process-lifetime cache mirrors the registry metadata caches so Models
    panel refreshes and alias peeks never repeat ``PATH`` scans per row.  A
    ``SASE_<PROVIDER>_PATH`` override takes precedence over the plugin's
    ``llm_autodetect_cli_name``.  Providers that declare no CLI are always
    available.

    Tests that change provider metadata, ``PATH``, or a provider-path override
    should call ``_provider_cli_available.cache_clear()``.
    """
    return _provider_cli_available_from_payload(
        provider_name,
        _llm_metadata_payload(),
        environ=os.environ,
        which=shutil.which,
    )


def capture_provider_disable_snapshot(
    now: float | None = None,
) -> dict[str, TemporaryProviderDisable]:
    """Capture active provider disables once for one routing operation."""
    return get_active_provider_disables(now)


def provider_disable_for(
    provider_name: str | None,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> TemporaryProviderDisable | None:
    """Return the active disable for *provider_name*, if one is captured."""
    if not provider_name:
        return None
    disables = (
        capture_provider_disable_snapshot()
        if provider_disables is None
        else provider_disables
    )
    return disables.get(provider_name)


def provider_routing_available(
    provider_name: str | None,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> bool:
    """Return whether a provider can be used by automatic routing."""
    if not provider_name or provider_name not in registered_provider_names():
        return False
    if provider_disable_for(provider_name, provider_disables) is not None:
        return False
    return _provider_cli_available(provider_name)


def build_provider_routing_statuses(
    provider_disables: ProviderDisableSnapshot | None = None,
) -> tuple[ProviderRoutingStatus, ...]:
    """Return raw provider routing state for provider-management UI surfaces."""
    disables = (
        capture_provider_disable_snapshot()
        if provider_disables is None
        else provider_disables
    )
    payload = _llm_metadata_payload()
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return ()
    hidden = model_picker_hidden_provider_names()
    model_counts = _provider_model_counts(payload)
    affected = _affected_aliases_by_provider()
    rows = [
        ProviderRoutingStatus(
            provider=provider,
            model_count=model_counts.get(provider, 0),
            cli_available=_provider_cli_available(provider),
            active_disable=disables.get(provider),
            hidden_from_model_pickers=provider in hidden,
            affected_aliases=affected.get(provider, ()),
        )
        for provider in sorted(str(name) for name in providers)
    ]
    return tuple(rows)


def _provider_model_counts(payload: Mapping[str, object]) -> dict[str, int]:
    return _provider_model_counts_from_payload(payload)


def raise_if_provider_temporarily_disabled(
    provider_name: str | None,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> None:
    """Raise the explicit dispatch diagnostic for a disabled provider."""
    if not provider_name or provider_name not in registered_provider_names():
        return
    disable = provider_disable_for(provider_name, provider_disables)
    if disable is not None:
        raise ProviderTemporarilyDisabledError(provider_name, disable)


def get_provider(
    name: str | None = None,
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> LLMProvider:
    """Get an instantiated LLM provider by name.

    Args:
        name: Provider name. If None, uses the default from config.

    Returns:
        An :class:`LLMPluginManager` wrapping the requested plugin.

    Raises:
        KeyError: If the provider name is not registered as an entry point.
    """
    if name is None:
        name = get_default_provider_name(provider_disables=provider_disables)
    raise_if_provider_temporarily_disabled(name, provider_disables)
    return create_provider(name)


def resolve_execution_provider_name(
    requested_provider: str | None = None,
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Return the provider that should execute an invocation.

    ``SASE_LLM_EXEC_PROVIDER`` deliberately changes only runtime dispatch. The
    requested provider and model remain the source of display and chat metadata.
    Registration is validated later by :func:`get_provider`, at the same lookup
    choke point used for ordinary invocations.
    """
    requested = requested_provider or get_default_provider_name(
        provider_disables=provider_disables
    )
    override = os.environ.get(LLM_EXEC_PROVIDER_ENV, "").strip()
    return override or requested


def resolve_model_provider(
    model_override: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
) -> tuple[str | None, str]:
    """Resolve a model override string to (provider_name, model_name).

    Supports three resolution strategies:

    1. Configured aliases: ``"other"`` → ``"claude/opus"``
    2. Explicit provider syntax: ``"codex/o3"`` → ``("codex", "o3")``
    3. Implicit via plugin metadata: ``"o3"`` → ``("codex", "o3")``

    If neither matches, returns ``(None, model_override)`` so the caller
    falls back to the default provider.

    Args:
        model_override: The raw model override string from ``%model`` directive.

    Returns:
        Tuple of (provider_name_or_none, clean_model_name).
    """
    provider, model, _ = resolve_model_provider_with_effort(
        model_override,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
    )
    return provider, model


def resolve_model_provider_with_effort(
    model_override: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
) -> tuple[str | None, str, str | None]:
    """Resolve a model override to provider/model plus alias-borne effort.

    Selector-backed targets retain their explicit provider prefix even when
    that provider is not registered. That lets authoritative launches fail at
    the normal provider lookup with an actionable diagnostic when every pool or
    fallback member is unavailable, instead of silently rerouting the model to
    the default provider.
    """
    provider, model, effort, _alias_trail = resolve_model_provider_with_trail(
        model_override,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
    )
    return provider, model, effort


def resolve_model_provider_with_trail(
    model_override: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
    model_tier: ModelTier = "large",
    provider_disables: ProviderDisableSnapshot | None = None,
) -> tuple[str | None, str, str | None, tuple[str, ...]]:
    """Resolve a model override to provider/model/effort plus alias hops."""
    resolved = resolve_model_alias_with_effort(
        model_override,
        model_alias_overrides,
        consume=consume,
        model_tier=model_tier,
        provider_disables=provider_disables,
    )
    model_override = resolved.target

    # 1. Check for explicit provider/model syntax
    if "/" in model_override:
        prefix, rest = model_override.split("/", 1)
        if prefix in _provider_names() or resolved.selector_alias is not None:
            return prefix, rest, resolved.effort, resolved.alias_trail

    # 2. Check the plugin-supplied model-to-provider map
    provider = model_to_provider_map().get(model_override)
    if provider:
        return provider, model_override, resolved.effort, resolved.alias_trail

    # 3. Unknown model — fall back to default provider
    return None, model_override, resolved.effort, resolved.alias_trail


def get_configured_default_provider_name(
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Get the configured/autodetected provider without temporary overrides."""
    config = get_llm_provider_config()
    provider = config.get("provider")
    if isinstance(provider, str) and provider:
        return provider

    disables = (
        capture_provider_disable_snapshot()
        if provider_disables is None
        else provider_disables
    )
    candidates = _llm_metadata_payload().get("autodetect_candidates")
    if not isinstance(candidates, list):
        candidates = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("provider"))
        if provider_routing_available(name, disables):
            return name

    raise RuntimeError(
        "No LLM provider is available. Install a provider plugin "
        "or set llm_provider.provider explicitly."
    )


def get_default_provider_name(
    *,
    provider_disables: ProviderDisableSnapshot | None = None,
) -> str:
    """Get the effective default provider name.

    An active temporary LLM override (see
    :mod:`sase.llm_provider.temporary_override`) wins over both the
    configured default and autodetect — it represents an explicit, recent
    user choice.  When no override is active, falls back to the configured
    default if set; otherwise walks registered plugins in
    ``llm_autodetect_priority`` order (ascending) and picks the first
    whose ``llm_autodetect_cli_name`` is on ``PATH``.  A plugin returning
    ``None`` from ``llm_autodetect_cli_name`` is always eligible, which is
    intended for non-CLI providers; built-in CLI providers declare a CLI name.

    Raises:
        RuntimeError: If no plugin declares an autodetect priority.
    """
    # Lazy import to avoid an import cycle: temporary_override imports
    # from this module's siblings via __init__.py.
    from .temporary_override import get_active_temporary_override

    disables = (
        capture_provider_disable_snapshot()
        if provider_disables is None
        else provider_disables
    )
    override = get_active_temporary_override()
    if (
        override is not None
        and provider_disable_for(override.provider, disables) is None
    ):
        return override.provider

    return get_configured_default_provider_name(provider_disables=disables)
