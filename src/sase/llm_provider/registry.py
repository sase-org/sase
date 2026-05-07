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
import shutil

import pluggy

from ._hookspec import LLMHookSpec
from ._plugin_manager import LLMPluginManager
from .base import LLMProvider
from .config import get_llm_provider_config

_PROVIDER_FAMILY_COLORS: dict[str, str] = {
    "claude": "#D97757",
    "anthropic": "#D97757",
    "gemini": "#4285F4",
    "codex": "#10A37F",
    "openai": "#10A37F",
}


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


def model_to_provider_map() -> dict[str, str]:
    """Build a ``{model_name → provider_name}`` map from plugin metadata."""
    mapping: dict[str, str] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_known_model_names", None)
        if method is None:
            continue
        models = method() or []
        for model in models:
            mapping[model] = name
    return mapping


def provider_short_name_map() -> dict[str, str]:
    """Return ``{provider_name → short_label}`` for agent-name suffixes.

    When a plugin doesn't implement ``llm_provider_short_name``, the
    fallback is its entry-point name — preserving today's behavior for
    plugins that haven't been updated.
    """
    mapping: dict[str, str] = {}
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_provider_short_name", None)
        short = method() if method is not None else None
        mapping[name] = short or name
    return mapping


def model_short_alias_map() -> dict[str, str]:
    """Build a ``{model_name → short_alias}`` map from plugin metadata.

    Each provider plugin may declare an ``llm_model_short_aliases`` hook
    returning a dict of long-form model names to short aliases used in
    multi-model agent name suffixes.  Last writer wins on duplicates.
    """
    mapping: dict[str, str] = {}
    for _, plugin in iter_plugins():
        method = getattr(plugin, "llm_model_short_aliases", None)
        if method is None:
            continue
        aliases = method() or {}
        mapping.update(aliases)
    return mapping


def provider_cli_status_color_map() -> dict[str, str]:
    """Return provider colors from plugin metadata, plus vendor-family defaults."""
    colors = dict(_PROVIDER_FAMILY_COLORS)
    for name, plugin in iter_plugins():
        method = getattr(plugin, "llm_cli_status_color", None)
        if method is None:
            continue
        color = method()
        if color:
            colors[name] = color
    return colors


def _provider_names() -> list[str]:
    """Return all registered provider names (entry-point keys)."""
    return [name for name, _ in iter_plugins()]


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

    Supports two resolution strategies:

    1. Explicit provider syntax: ``"codex/o3"`` → ``("codex", "o3")``
    2. Implicit via plugin metadata: ``"o3"`` → ``("codex", "o3")``

    If neither matches, returns ``(None, model_override)`` so the caller
    falls back to the default provider.

    Args:
        model_override: The raw model override string from ``%model`` directive.

    Returns:
        Tuple of (provider_name_or_none, clean_model_name).
    """
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

    candidates: list[tuple[int, str, str | None]] = []
    for name, plugin in iter_plugins():
        prio_method = getattr(plugin, "llm_autodetect_priority", None)
        if prio_method is None:
            continue
        priority = prio_method()
        if priority is None:
            continue
        cli_method = getattr(plugin, "llm_autodetect_cli_name", None)
        cli_name = cli_method() if cli_method is not None else None
        candidates.append((priority, name, cli_name))

    candidates.sort()
    for _, name, cli_name in candidates:
        if cli_name is None or shutil.which(cli_name):
            return name

    raise RuntimeError(
        "No LLM provider is available. Install a provider plugin "
        "or set llm_provider.provider explicitly."
    )
