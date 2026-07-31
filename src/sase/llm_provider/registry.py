"""Provider registry for LLM backends.

Providers are discovered by :mod:`sase.llm_provider._registry_plugins` via
``importlib.metadata.entry_points(group="sase_llm")``. Metadata normalization
and cache fingerprints live in :mod:`sase.llm_provider._registry_metadata`.
This module remains the stable façade for registry access and model resolution.

Dispatch uses a single-plugin :class:`pluggy.PluginManager` so only the
selected provider's ``llm_invoke`` hook fires.  Metadata lookups (known
model names, skill deploy paths, auto-detection, retry defaults, ...)
share a memoized multi-plugin PM built by :func:`_build_llm_pm`, and
callers iterate ``pm.list_name_plugin()`` to collect per-plugin values.
"""

import functools
import os
from pathlib import Path
import shutil
from collections.abc import Mapping
from typing import Any

import pluggy

from ._registry_metadata import (
    llm_metadata_cache_policy,
    normalize_str_dict,
    provider_metadata,
    provider_path_env_var,
)
from ._registry_plugins import (
    build_llm_plugin_manager,
    create_provider,
)
from .base import LLMProvider
from .config import (
    get_llm_provider_config,
    resolve_model_alias_with_effort,
)
from .types import ModelTier

_PROVIDER_FAMILY_COLORS: dict[str, str] = {
    "claude": "#D97757",
    "anthropic": "#D97757",
    "codex": "#10A37F",
    "openai": "#10A37F",
}

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

    providers: dict[str, dict[str, Any]] = {}
    model_to_provider: dict[str, str] = {}
    provider_short_names: dict[str, str] = {}
    model_short_aliases: dict[str, str] = {}
    provider_colors = dict(_PROVIDER_FAMILY_COLORS)
    autodetect_candidates: list[dict[str, Any]] = []
    default_retry_configs: dict[str, dict[str, Any]] = {}

    for name, plugin in iter_plugins():
        provider_metadata = _provider_metadata(name, plugin)
        providers[name] = provider_metadata

        for model in provider_metadata["known_model_names"]:
            model_to_provider[model] = name

        provider_short_names[name] = provider_metadata["short_name"] or name
        model_short_aliases.update(provider_metadata["model_short_aliases"])
        color = provider_metadata["cli_status_color"]
        if color:
            provider_colors[name] = color

        priority = provider_metadata["autodetect_priority"]
        if priority is not None:
            autodetect_candidates.append(
                {
                    "priority": priority,
                    "provider": name,
                    "cli_name": provider_metadata["autodetect_cli_name"],
                }
            )

        retry_config = provider_metadata["default_retry_config"]
        if retry_config is not None:
            default_retry_configs[name] = retry_config

    autodetect_candidates.sort(
        key=lambda item: (int(item["priority"]), str(item["provider"]))
    )
    return {
        "schema_version": 1,
        "providers": providers,
        "provider_names": sorted(providers),
        "model_to_provider": model_to_provider,
        "provider_short_names": provider_short_names,
        "model_short_aliases": model_short_aliases,
        "provider_cli_status_colors": provider_colors,
        "autodetect_candidates": autodetect_candidates,
        "default_retry_configs": default_retry_configs,
        "cache_invalidation": _llm_metadata_cache_policy(),
    }


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
    return normalize_str_dict(_llm_metadata_payload().get("model_to_provider"))


def provider_short_name_map() -> dict[str, str]:
    """Return ``{provider_name → short_label}`` for agent-name suffixes.

    When a plugin doesn't implement ``llm_provider_short_name``, the
    fallback is its entry-point name — preserving today's behavior for
    plugins that haven't been updated.
    """
    return normalize_str_dict(_llm_metadata_payload().get("provider_short_names"))


def model_short_alias_map() -> dict[str, str]:
    """Build a ``{model_name → short_alias}`` map from plugin metadata.

    Each provider plugin may declare an ``llm_model_short_aliases`` hook
    returning a dict of long-form model names to short aliases used in
    multi-model agent name suffixes.  Last writer wins on duplicates.
    """
    return normalize_str_dict(_llm_metadata_payload().get("model_short_aliases"))


def provider_cli_status_color_map() -> dict[str, str]:
    """Return provider colors from plugin metadata, plus vendor-family defaults."""
    return normalize_str_dict(_llm_metadata_payload().get("provider_cli_status_colors"))


def model_picker_hidden_provider_names() -> frozenset[str]:
    """Return provider names flagged as hidden from user-facing model pickers.

    Driven by the ``llm_hidden_from_model_pickers`` plugin hook rather than a
    hardcoded provider name, so any provider (built-in or third-party) that
    exists only for testing can opt out of the ACE model picker and ``%model``
    completion catalog while remaining fully registered and routable.
    """
    providers = _llm_metadata_payload().get("providers")
    if not isinstance(providers, dict):
        return frozenset()
    return frozenset(
        name
        for name, metadata in providers.items()
        if isinstance(metadata, dict)
        and metadata.get("hidden_from_model_pickers") is True
    )


def _provider_names() -> list[str]:
    """Return all registered provider names (entry-point keys)."""
    names = _llm_metadata_payload().get("provider_names")
    if not isinstance(names, list):
        return []
    return [str(name) for name in names]


def registered_provider_names() -> list[str]:
    """Return all registered LLM provider names (entry-point keys).

    Public adapter over :func:`_provider_names` for callers outside the
    registry (e.g. the model alias policy in :mod:`sase.llm_provider.config`)
    that need the set of providers without reaching into private helpers.
    """
    return _provider_names()


@functools.cache
def provider_cli_available(provider_name: str) -> bool:
    """Return whether a registered provider's declared CLI is installed.

    The process-lifetime cache mirrors the registry metadata caches so Models
    panel refreshes and alias peeks never repeat ``PATH`` scans per row.  A
    ``SASE_<PROVIDER>_PATH`` override takes precedence over the plugin's
    ``llm_autodetect_cli_name``.  Providers that declare no CLI are always
    available.

    Tests that change provider metadata, ``PATH``, or a provider-path override
    should call ``provider_cli_available.cache_clear()``.
    """
    providers = _llm_metadata_payload().get("providers")
    if not isinstance(providers, dict):
        return False
    metadata = providers.get(provider_name)
    if not isinstance(metadata, dict):
        return False
    cli_name = metadata.get("autodetect_cli_name")
    if cli_name is not None:
        cli_name = str(cli_name).strip() or None
    override = os.environ.get(provider_path_env_var(provider_name), "").strip()
    command = override or cli_name
    if command is None:
        return True
    expanded = os.path.expanduser(command)
    if shutil.which(expanded) is not None:
        return True
    if os.sep in expanded:
        candidate = Path(expanded)
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return False


def get_provider(name: str | None = None) -> LLMProvider:
    """Get an instantiated LLM provider by name.

    Args:
        name: Provider name. If None, uses the default from config.

    Returns:
        An :class:`LLMPluginManager` wrapping the requested plugin.

    Raises:
        KeyError: If the provider name is not registered as an entry point.
    """
    if name is None:
        name = get_default_provider_name()
    return create_provider(name)


def resolve_execution_provider_name(requested_provider: str | None = None) -> str:
    """Return the provider that should execute an invocation.

    ``SASE_LLM_EXEC_PROVIDER`` deliberately changes only runtime dispatch. The
    requested provider and model remain the source of display and chat metadata.
    Registration is validated later by :func:`get_provider`, at the same lookup
    choke point used for ordinary invocations.
    """
    requested = requested_provider or get_default_provider_name()
    override = os.environ.get(LLM_EXEC_PROVIDER_ENV, "").strip()
    return override or requested


def resolve_model_provider(
    model_override: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
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
    )
    return provider, model


def resolve_model_provider_with_effort(
    model_override: str,
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str | None, str, str | None]:
    """Resolve a model override to provider/model plus alias-borne effort.

    Selector-backed targets retain their explicit provider prefix even when
    that provider is not registered. That lets authoritative launches fail at
    the normal provider lookup with an actionable diagnostic when every pool or
    fallback member is unavailable, instead of silently rerouting the model to
    the default provider.
    """
    resolved = resolve_model_alias_with_effort(
        model_override,
        model_alias_overrides,
        consume=consume,
    )
    model_override = resolved.target

    # 1. Check for explicit provider/model syntax
    if "/" in model_override:
        prefix, rest = model_override.split("/", 1)
        if prefix in _provider_names() or resolved.selector_alias is not None:
            return prefix, rest, resolved.effort

    # 2. Check the plugin-supplied model-to-provider map
    provider = model_to_provider_map().get(model_override)
    if provider:
        return provider, model_override, resolved.effort

    # 3. Unknown model — fall back to default provider
    return None, model_override, resolved.effort


def resolve_default_alias_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str]:
    """Resolve the implicit ``@default`` alias to ``(provider, model)``.

    An active temporary ``default`` override wins and ignores *model_tier*.
    Otherwise, honors a configured
    ``llm_provider.model_aliases.builtin.default`` target (which may itself
    chain through other aliases via ``@``), then falls back to the configured
    or autodetected provider's *model_tier* default.
    """
    from .temporary_override import get_active_alias_override

    override = get_active_alias_override("default")
    if override is not None:
        return override.provider, override.model

    from .config import default_model_alias_name, get_model_aliases

    configured = get_model_aliases().get(default_model_alias_name())
    if configured:
        provider, model = resolve_model_provider(
            f"@{default_model_alias_name()}",
            model_alias_overrides,
            consume=consume,
        )
        if provider is not None:
            return provider, model
        # Configured default is a bare/unknown model: run it on the configured
        # provider rather than silently dropping the user's choice.
        return get_configured_default_provider_name(), model

    provider_name = get_configured_default_provider_name()
    return provider_name, get_provider(provider_name).resolve_model_name(model_tier)


def resolve_default_alias_provider_model_with_effort(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
    *,
    consume: bool = False,
) -> tuple[str, str, str | None]:
    """Resolve ``@default`` including temporary overrides and alias effort.

    An active temporary override wins and ignores *model_tier*.
    """
    from .temporary_override import get_active_alias_override

    override = get_active_alias_override("default")
    if override is not None:
        return override.provider, override.model, override.effort

    from .config import default_model_alias_name, get_model_aliases

    configured = get_model_aliases().get(default_model_alias_name())
    if configured:
        provider, model, effort = resolve_model_provider_with_effort(
            f"@{default_model_alias_name()}",
            model_alias_overrides,
            consume=consume,
        )
        if provider is not None:
            return provider, model, effort
        # Configured default is a bare/unknown model: run it on the configured
        # provider rather than silently dropping the user's choice.
        return get_configured_default_provider_name(), model, effort

    provider_name, model = resolve_default_alias_provider_model(
        model_tier,
        model_alias_overrides,
        consume=consume,
    )
    return provider_name, model, None


def format_provider_model_label(
    llm_provider: str | None = None,
    model: str | None = None,
) -> str:
    """Format provider and model as PROVIDER(model), e.g. 'CLAUDE(opus)'.

    Falls back to 'Agent' if neither is available.
    """
    if llm_provider and model:
        return f"{llm_provider.upper()}({model})"
    if llm_provider:
        return llm_provider.upper()
    if model:
        return model
    return "Agent"


def get_configured_default_provider_name() -> str:
    """Get the configured/autodetected provider without temporary overrides."""
    config = get_llm_provider_config()
    provider = config.get("provider")
    if isinstance(provider, str) and provider:
        return provider

    candidates = _llm_metadata_payload().get("autodetect_candidates")
    if not isinstance(candidates, list):
        candidates = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("provider"))
        cli_name = item.get("cli_name")
        if cli_name is not None:
            cli_name = str(cli_name)
        if cli_name is None or shutil.which(cli_name):
            return name

    raise RuntimeError(
        "No LLM provider is available. Install a provider plugin "
        "or set llm_provider.provider explicitly."
    )


def get_default_provider_name() -> str:
    """Get the effective default provider name.

    An active temporary LLM override (see
    :mod:`sase.llm_provider.temporary_override`) wins over both the
    configured default and autodetect — it represents an explicit, recent
    user choice.  When no override is active, falls back to the configured
    default if set; otherwise walks registered plugins in
    ``llm_autodetect_priority`` order (ascending) and picks the first
    whose ``llm_autodetect_cli_name`` is on ``PATH``.  A plugin returning
    ``None`` from ``llm_autodetect_cli_name`` is always eligible, which is
    intended for non-CLI providers; built-in CLI providers declare a ChangeSpecI name.

    Raises:
        RuntimeError: If no plugin declares an autodetect priority.
    """
    # Lazy import to avoid an import cycle: temporary_override imports
    # from this module's siblings via __init__.py.
    from .temporary_override import get_active_temporary_override

    override = get_active_temporary_override()
    if override is not None:
        return override.provider

    return get_configured_default_provider_name()
