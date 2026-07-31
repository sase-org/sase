"""Plugin discovery and construction for the LLM provider registry."""

import importlib.metadata

import pluggy

from ._hookspec import LLMHookSpec
from ._plugin_manager import LLMPluginManager


def build_llm_plugin_manager() -> pluggy.PluginManager:
    """Build a plugin manager containing every ``sase_llm`` plugin."""
    pm = pluggy.PluginManager("sase_llm")
    pm.add_hookspecs(LLMHookSpec)
    for ep in importlib.metadata.entry_points(group="sase_llm"):
        plugin_class = ep.load()
        pm.register(plugin_class(), name=ep.name)
    return pm


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


def create_provider(name: str) -> LLMPluginManager:
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
