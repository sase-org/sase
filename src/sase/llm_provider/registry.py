"""Provider registry for LLM backends.

Providers are discovered via ``importlib.metadata.entry_points(group="sase_llm")``
(mirroring the VCS plugin layer in :mod:`sase.vcs_provider._registry`). Each
entry point resolves to a plugin class that implements the ``sase_llm`` hook
specifications (see :mod:`sase.llm_provider._hookspec`).

Dispatch uses a single-plugin :class:`pluggy.PluginManager` so only the
selected provider's ``llm_invoke`` hook fires.  Metadata lookups (known
model names, skill deploy paths, auto-detection, retry defaults, ...)
share a memoized multi-plugin PM built by :func:`_build_llm_pm`, and
callers iterate ``pm.list_name_plugin()`` to collect per-plugin values.
"""

import functools
import importlib.metadata
import os
import shutil
import time
from dataclasses import asdict, is_dataclass
from typing import Any

import pluggy

from sase.host.client import call_provider_host, is_host_fallbackable
from sase.host.routing import (
    host_required,
    host_routing_mode,
    record_shadow_comparison,
)
from sase.host.wire import HOST_CAP_LLM_METADATA

from ._hookspec import LLMHookSpec
from ._plugin_manager import LLMPluginManager
from .base import LLMProvider
from .config import get_llm_provider_config, resolve_model_alias

_PROVIDER_FAMILY_COLORS: dict[str, str] = {
    "claude": "#D97757",
    "anthropic": "#D97757",
    "gemini": "#4285F4",
    "codex": "#10A37F",
    "openai": "#10A37F",
}
_LLM_METADATA_OPERATION = "llm.metadata"
_LLM_METADATA_DISABLE_ENV = "SASE_DISABLE_HOST_LLM_METADATA"
_LLM_METADATA_TIMEOUT_MS = 1_000
_LLM_METADATA_HOST_FALLBACK_RETRY_S = 30.0
_llm_metadata_host_cached_payload: dict[str, Any] | None = None
_llm_metadata_host_cached_call_id: int | None = None
_llm_metadata_host_fallback_until = 0.0
_llm_metadata_host_fallback_call_id: int | None = None


@functools.cache
def _build_llm_pm() -> pluggy.PluginManager:
    """Return a shared :class:`pluggy.PluginManager` with every ``sase_llm`` plugin.

    Memoized for the process lifetime: entry-point discovery is walked
    exactly once.  Tests that mock entry points must clear the cache via
    ``_build_llm_pm.cache_clear()``.
    """
    pm = pluggy.PluginManager("sase_llm")
    pm.add_hookspecs(LLMHookSpec)
    for ep in importlib.metadata.entry_points(group="sase_llm"):
        plugin_class = ep.load()
        pm.register(plugin_class(), name=ep.name)
    return pm


def iter_plugins() -> list[tuple[str, object]]:
    """Return registered ``(provider_name, plugin_instance)`` pairs."""
    return list(_build_llm_pm().list_name_plugin())


def direct_llm_metadata_payload() -> dict[str, Any]:
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


def llm_metadata_payload() -> dict[str, Any]:
    """Return routed LLM metadata with direct Python fallback."""

    operation = _LLM_METADATA_OPERATION
    mode = (
        "direct"
        if os.environ.get(_LLM_METADATA_DISABLE_ENV)
        else host_routing_mode(operation)
    )
    if mode == "shadow":
        direct = direct_llm_metadata_payload()
        try:
            response = call_provider_host(
                family="llm",
                operation=operation,
                payload={},
                required_capability=HOST_CAP_LLM_METADATA,
                timeout_ms=_LLM_METADATA_TIMEOUT_MS,
            )
            host = dict(response.result) if response.status == "ok" else None
            record_shadow_comparison(operation, direct=direct, host=host)
        except Exception as error:
            if not is_host_fallbackable(error):
                raise
            record_shadow_comparison(operation, direct=direct, error=error)
        return direct

    if mode in {"host-preferred", "host-required"}:
        cached = _llm_metadata_cached_host_payload()
        if cached is not None:
            return cached
        if mode == "host-preferred" and _llm_metadata_host_fallback_active():
            return direct_llm_metadata_payload()
        try:
            response = call_provider_host(
                family="llm",
                operation=operation,
                payload={},
                required_capability=HOST_CAP_LLM_METADATA,
                timeout_ms=_LLM_METADATA_TIMEOUT_MS,
            )
            if response.status == "ok":
                payload = dict(response.result)
                _remember_llm_metadata_host_payload(payload)
                return payload
            _remember_llm_metadata_host_fallback()
        except Exception as error:
            if host_required(operation) or not is_host_fallbackable(error):
                raise
            _remember_llm_metadata_host_fallback()
    return direct_llm_metadata_payload()


def _llm_metadata_cached_host_payload() -> dict[str, Any] | None:
    if (
        _llm_metadata_host_cached_call_id == id(call_provider_host)
        and _llm_metadata_host_cached_payload is not None
    ):
        return dict(_llm_metadata_host_cached_payload)
    return None


def _remember_llm_metadata_host_payload(payload: dict[str, Any]) -> None:
    global _llm_metadata_host_cached_call_id
    global _llm_metadata_host_cached_payload
    _llm_metadata_host_cached_call_id = id(call_provider_host)
    _llm_metadata_host_cached_payload = dict(payload)


def _llm_metadata_host_fallback_active() -> bool:
    return (
        _llm_metadata_host_fallback_call_id == id(call_provider_host)
        and time.monotonic() < _llm_metadata_host_fallback_until
    )


def _remember_llm_metadata_host_fallback() -> None:
    global _llm_metadata_host_fallback_call_id
    global _llm_metadata_host_fallback_until
    _llm_metadata_host_fallback_call_id = id(call_provider_host)
    _llm_metadata_host_fallback_until = (
        time.monotonic() + _LLM_METADATA_HOST_FALLBACK_RETRY_S
    )


def model_to_provider_map() -> dict[str, str]:
    """Build a ``{model_name → provider_name}`` map from plugin metadata."""
    return _str_dict(llm_metadata_payload().get("model_to_provider"))


def provider_short_name_map() -> dict[str, str]:
    """Return ``{provider_name → short_label}`` for agent-name suffixes.

    When a plugin doesn't implement ``llm_provider_short_name``, the
    fallback is its entry-point name — preserving today's behavior for
    plugins that haven't been updated.
    """
    return _str_dict(llm_metadata_payload().get("provider_short_names"))


def model_short_alias_map() -> dict[str, str]:
    """Build a ``{model_name → short_alias}`` map from plugin metadata.

    Each provider plugin may declare an ``llm_model_short_aliases`` hook
    returning a dict of long-form model names to short aliases used in
    multi-model agent name suffixes.  Last writer wins on duplicates.
    """
    return _str_dict(llm_metadata_payload().get("model_short_aliases"))


def provider_cli_status_color_map() -> dict[str, str]:
    """Return provider colors from plugin metadata, plus vendor-family defaults."""
    return _str_dict(llm_metadata_payload().get("provider_cli_status_colors"))


def _provider_names() -> list[str]:
    """Return all registered provider names (entry-point keys)."""
    names = llm_metadata_payload().get("provider_names")
    if not isinstance(names, list):
        return []
    return [str(name) for name in names]


def _find_plugin_class(name: str) -> type | None:
    """Look up an LLM plugin class by name from ``sase_llm`` entry points.

    Args:
        name: The entry-point name to find (e.g. ``"claude"``).

    Returns:
        The plugin class, or ``None`` if no matching entry point exists.
    """
    for ep in importlib.metadata.entry_points(group="sase_llm"):
        if ep.name == name:
            return ep.load()  # type: ignore[no-any-return]
    return None


def _create_provider_for(name: str) -> LLMPluginManager:
    """Create an :class:`LLMPluginManager` for *name* via entry points.

    Args:
        name: Provider name (e.g. ``"claude"``, ``"codex"``).

    Raises:
        KeyError: If no entry point matches *name*.
    """
    plugin_class = _find_plugin_class(name)
    if plugin_class is None:
        available = sorted(
            ep.name for ep in importlib.metadata.entry_points(group="sase_llm")
        )
        raise KeyError(
            f"Unknown LLM provider: {name!r}. Registered providers: {available}"
        )

    pm = pluggy.PluginManager("sase_llm")
    pm.add_hookspecs(LLMHookSpec)
    pm.register(plugin_class())
    return LLMPluginManager(pm)


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
    return _create_provider_for(name)


def resolve_model_provider(model_override: str) -> tuple[str | None, str]:
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
    model_override = resolve_model_alias(model_override)

    # 1. Check for explicit provider/model syntax
    if "/" in model_override:
        prefix, rest = model_override.split("/", 1)
        if prefix in _provider_names():
            return prefix, rest

    # 2. Check the plugin-supplied model-to-provider map
    provider = model_to_provider_map().get(model_override)
    if provider:
        return provider, model_override

    # 3. Unknown model — fall back to default provider
    return None, model_override


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


def get_default_provider_name() -> str:
    """Get the effective default provider name.

    An active temporary LLM override (see
    :mod:`sase.llm_provider.temporary_override`) wins over both the
    configured default and autodetect — it represents an explicit, recent
    user choice.  When no override is active, falls back to the configured
    default if set; otherwise walks registered plugins in
    ``llm_autodetect_priority`` order (ascending) and picks the first
    whose ``llm_autodetect_cli_name`` is on ``PATH``.  A plugin returning
    ``None`` from ``llm_autodetect_cli_name`` is always eligible (used by
    gemini as the final fallback).

    Raises:
        RuntimeError: If no plugin declares an autodetect priority.
    """
    # Lazy import to avoid an import cycle: temporary_override imports
    # from this module's siblings via __init__.py.
    from .temporary_override import get_active_temporary_override

    override = get_active_temporary_override()
    if override is not None:
        return override.provider

    config = get_llm_provider_config()
    provider = config.get("provider")
    if provider:
        return provider

    candidates = llm_metadata_payload().get("autodetect_candidates")
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


def _llm_metadata_cache_policy() -> dict[str, Any]:
    """Return cache invalidation inputs for host-routed LLM metadata."""

    env_names = (
        "SASE_DISABLE_PLUGINS",
        "SASE_DISABLE_PLUGIN_LLM",
        "SASE_CLAUDE_PATH",
        "SASE_CODEX_PATH",
        "SASE_GEMINI_PATH",
        "SASE_OPENCODE_PATH",
        "SASE_QWEN_PATH",
    )
    return {
        "version": 1,
        "plugin_entry_points": [
            {"name": ep.name, "value": ep.value}
            for ep in sorted(
                importlib.metadata.entry_points(group="sase_llm"),
                key=lambda item: item.name,
            )
        ],
        "environment": {name: os.environ.get(name) for name in env_names},
        "config": _config_fingerprint(),
    }


def _provider_metadata(name: str, plugin: object) -> dict[str, Any]:
    provider_name = _call_optional(plugin, "llm_provider_name")
    short_name = _call_optional(plugin, "llm_provider_short_name") or name
    known_models = _call_optional(plugin, "llm_known_model_names") or []
    model_aliases = _call_optional(plugin, "llm_model_short_aliases") or {}
    retry_config = _call_optional(plugin, "llm_default_retry_config")

    model_resolutions: dict[str, str] = {}
    resolve_model = getattr(plugin, "llm_resolve_model_name", None)
    if resolve_model is not None:
        for tier in ("large", "small"):
            try:
                model_resolutions[tier] = str(resolve_model(tier))
            except Exception:
                continue

    return {
        "provider_name": provider_name or name,
        "short_name": short_name,
        "known_model_names": [str(model) for model in known_models],
        "model_short_aliases": _str_dict(model_aliases),
        "skill_template_context": _str_dict(
            _call_optional(plugin, "llm_skill_template_context") or {}
        ),
        "skill_deploy_subpath": _call_optional(plugin, "llm_skill_deploy_subpath"),
        "cli_status_color": _call_optional(plugin, "llm_cli_status_color"),
        "autodetect_priority": _call_optional(plugin, "llm_autodetect_priority"),
        "autodetect_cli_name": _call_optional(plugin, "llm_autodetect_cli_name"),
        "default_retry_config": _dataclass_to_dict(retry_config),
        "model_resolutions": model_resolutions,
    }


def _call_optional(plugin: object, method_name: str) -> Any:
    method = getattr(plugin, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:
        return None


def _dataclass_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return dict(asdict(value))  # type: ignore[arg-type]
    if isinstance(value, dict):
        return dict(value)
    return None


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _config_fingerprint() -> dict[str, Any]:
    paths = (
        os.path.expanduser("~/.config/sase/sase.yml"),
        os.path.join(os.getcwd(), "sase.yml"),
    )
    result: dict[str, Any] = {}
    for raw_path in paths:
        try:
            stat = os.stat(raw_path)
        except OSError:
            result[raw_path] = {"exists": False}
            continue
        result[raw_path] = {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    return result
