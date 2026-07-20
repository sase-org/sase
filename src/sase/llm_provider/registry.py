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
import re
import shutil
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import pluggy

from ._hookspec import LLMHookSpec
from ._plugin_manager import LLMPluginManager
from .base import LLMProvider
from .config import get_llm_provider_config, resolve_model_alias
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
    return _str_dict(_llm_metadata_payload().get("model_to_provider"))


def provider_short_name_map() -> dict[str, str]:
    """Return ``{provider_name → short_label}`` for agent-name suffixes.

    When a plugin doesn't implement ``llm_provider_short_name``, the
    fallback is its entry-point name — preserving today's behavior for
    plugins that haven't been updated.
    """
    return _str_dict(_llm_metadata_payload().get("provider_short_names"))


def model_short_alias_map() -> dict[str, str]:
    """Build a ``{model_name → short_alias}`` map from plugin metadata.

    Each provider plugin may declare an ``llm_model_short_aliases`` hook
    returning a dict of long-form model names to short aliases used in
    multi-model agent name suffixes.  Last writer wins on duplicates.
    """
    return _str_dict(_llm_metadata_payload().get("model_short_aliases"))


def provider_cli_status_color_map() -> dict[str, str]:
    """Return provider colors from plugin metadata, plus vendor-family defaults."""
    return _str_dict(_llm_metadata_payload().get("provider_cli_status_colors"))


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
    model_override = resolve_model_alias(model_override, model_alias_overrides)

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


def resolve_default_alias_provider_model(
    model_tier: ModelTier = "large",
    model_alias_overrides: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve the implicit ``@default`` alias to ``(provider, model)``.

    Honors a configured ``llm_provider.model_aliases.builtin.default`` target
    (which may itself chain through other aliases via ``@``); otherwise falls
    back to the configured or autodetected provider's *model_tier* default. This
    is the no-``%model`` launch default, minus any temporary override — callers
    that want the override to win (the new-launch default behavior) go through
    :func:`sase.llm_provider.temporary_override.resolve_effective_default_provider_model`,
    which applies the override first and then delegates here.
    """
    from .config import default_model_alias_name, get_model_aliases

    configured = get_model_aliases().get(default_model_alias_name())
    if configured:
        provider, model = resolve_model_provider(configured, model_alias_overrides)
        if provider is not None:
            return provider, model
        # Configured default is a bare/unknown model: run it on the configured
        # provider rather than silently dropping the user's choice.
        return get_configured_default_provider_name(), model

    provider_name = get_configured_default_provider_name()
    return provider_name, get_provider(provider_name).resolve_model_name(model_tier)


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


def provider_path_env_var(provider_name: str) -> str:
    """Return the ``SASE_<PROVIDER>_PATH`` executable-override env var name.

    The provider name is upper-cased with runs of non-alphanumeric characters
    collapsed to a single underscore (e.g. ``"agy"`` -> ``"SASE_AGY_PATH"``).
    This is the single canonical derivation shared by the registry cache
    policy and the ``sase doctor`` provider checks, so registering a new
    provider never requires extending a hardcoded env-var list.
    """
    token = re.sub(r"[^A-Za-z0-9]+", "_", provider_name).strip("_").upper()
    return f"SASE_{token}_PATH"


def _llm_metadata_cache_policy() -> dict[str, Any]:
    """Return cache invalidation inputs for host-routed LLM metadata."""

    entry_points = sorted(
        importlib.metadata.entry_points(group="sase_llm"),
        key=lambda item: item.name,
    )
    # Derive each provider's SASE_<PROVIDER>_PATH override from the registered
    # entry points (deduped, order-preserving) so a new provider's path env var
    # participates in cache invalidation without editing a hardcoded list.
    static_env_names = ("SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_LLM")
    provider_path_envs = dict.fromkeys(
        provider_path_env_var(ep.name) for ep in entry_points
    )
    env_names = (*static_env_names, *provider_path_envs)
    return {
        "version": 1,
        "plugin_entry_points": [
            {"name": ep.name, "value": ep.value} for ep in entry_points
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
    auth_evidence = _auth_evidence_metadata(_call_optional(plugin, "llm_auth_evidence"))
    install_metadata = _install_metadata(_call_optional(plugin, "llm_install_metadata"))

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
        "additional_skill_deploy_subpaths": _str_list(
            _call_optional(plugin, "llm_additional_skill_deploy_subpaths")
        ),
        "cli_status_color": _call_optional(plugin, "llm_cli_status_color"),
        "autodetect_priority": _call_optional(plugin, "llm_autodetect_priority"),
        "autodetect_cli_name": _call_optional(plugin, "llm_autodetect_cli_name"),
        "auth_evidence": auth_evidence,
        "install": install_metadata,
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


def _auth_evidence_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "credential_paths": [],
            "api_key_env_vars": [],
            "auth_not_required": False,
        }
    return {
        "credential_paths": _str_list(value.get("credential_paths")),
        "api_key_env_vars": _str_list(value.get("api_key_env_vars")),
        "auth_not_required": value.get("auth_not_required") is True,
    }


def _install_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    metadata: dict[str, Any] = {
        "manager": _optional_str(value.get("manager")),
        "package": _optional_str(value.get("package")),
        "scope": _optional_str(value.get("scope")),
    }
    for key in (
        "display_name",
        "docs_url",
        "version_regex",
        "latest_version_package",
        "brew_package",
    ):
        if (normalized := _optional_str(value.get(key))) is not None:
            metadata[key] = normalized
    if argv := _argv_metadata(value.get("self_update_argv")):
        metadata["self_update_argv"] = argv
    if "version_argv" in value:
        metadata["version_argv"] = _argv_metadata(
            value.get("version_argv"), default=("--version",)
        )
    return metadata


def _argv_metadata(value: Any, *, default: tuple[str, ...] = ()) -> list[str]:
    if not isinstance(value, list | tuple):
        return list(default)
    argv = [str(item).strip() for item in value if str(item).strip()]
    return argv or list(default)


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _config_fingerprint() -> dict[str, Any]:
    from sase.content_layout import discover_project_root, resolve_project_layout

    paths = [os.path.expanduser("~/.config/sase/sase.yml")]
    project_root = discover_project_root()
    if project_root is not None:
        paths.extend(
            str(path) for path in resolve_project_layout(project_root).config.candidates
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
