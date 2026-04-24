"""Provider registry for LLM backends.

Providers are discovered via ``importlib.metadata.entry_points(group="sase_llm")``
(mirroring the VCS plugin layer in :mod:`sase.vcs_provider._registry`). Each
entry point resolves to a plugin class that implements the ``sase_llm`` hook
specifications (see :mod:`sase.llm_provider._hookspec`).
"""

import importlib.metadata
import re
import shutil

import pluggy

from ._hookspec import LLMHookSpec
from ._plugin_manager import LLMPluginManager
from .base import LLMProvider
from .config import get_llm_provider_config

# Model name to provider name mapping for automatic provider resolution.
# When %model specifies a known model name, the correct provider is auto-selected.
_MODEL_TO_PROVIDER: dict[str, str] = {
    # Claude models
    "opus": "claude",
    "sonnet": "claude",
    "haiku": "claude",
    # Codex / OpenAI models
    "gpt-5.3-codex": "codex",
    "codex-mini-latest": "codex",
    "o3": "codex",
    "o4-mini": "codex",
    "gpt-5.4": "codex",
    "gpt-4.1": "codex",
    "gpt-4.1-mini": "codex",
    "gpt-4o": "codex",
    "gpt-4o-mini": "codex",
    # Gemini models
    "gemini-2.5-pro": "gemini",
    "gemini-2.5-flash": "gemini",
    "gemini-3.1-pro": "gemini",
    "gemini-3.1-pro-preview": "gemini",
    "gemini-3-flash-preview": "gemini",
    "gemini-2.0-flash": "gemini",
    # Jetski models
    "jetski-default": "jetski",
}

# Pattern for explicit provider/model syntax, e.g. "codex/o3"
_PROVIDER_MODEL_RE = re.compile(r"^(claude|codex|gemini|jetski)/(.+)$")


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
    2. Implicit via mapping: ``"o3"`` → ``("codex", "o3")``

    If neither matches, returns ``(None, model_override)`` so the caller
    falls back to the default provider.

    Args:
        model_override: The raw model override string from ``%model`` directive.

    Returns:
        Tuple of (provider_name_or_none, clean_model_name).
    """
    # 1. Check for explicit provider/model syntax
    match = _PROVIDER_MODEL_RE.match(model_override)
    if match:
        return match.group(1), match.group(2)

    # 2. Check the model-to-provider mapping
    provider = _MODEL_TO_PROVIDER.get(model_override)
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
    """Get the default provider name from configuration.

    Returns:
        The configured default provider name, or auto-detected provider.
        Auto-detect priority: claude → codex → jetski → gemini.
    """
    config = get_llm_provider_config()
    provider = config.get("provider")
    if provider:
        return provider
    if shutil.which("claude"):
        return "claude"
    if shutil.which("codex"):
        return "codex"
    if shutil.which("jetski-cli"):
        return "jetski"
    return "gemini"
