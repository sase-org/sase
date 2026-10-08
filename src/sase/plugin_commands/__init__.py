"""Plugin-mounted top-level commands (``sase <name>``).

A distribution mounts a command by declaring one entry point per command in
the ``sase_commands`` group; the entry-point name is the command name and the
value is a ``module`` (or ``module:object``) exposing ``main`` and
``build_parser``. See :mod:`sase.plugin_commands.scan`,
:mod:`sase.plugin_commands.registry`, :mod:`sase.plugin_commands.adapter`,
:mod:`sase.plugin_commands.dispatch`, :mod:`sase.plugin_commands.chip`, and
:mod:`sase.plugin_commands.hints`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.plugin_commands.adapter import LoadedPluginCommand, PluginCommandLoadError
    from sase.plugin_commands.registry import PluginCommandProblem, PluginCommandSet
    from sase.plugin_commands.scan import PluginCommandRecord

__all__ = [
    "LoadedPluginCommand",
    "PluginCommandLoadError",
    "PluginCommandProblem",
    "PluginCommandRecord",
    "PluginCommandSet",
]


def __getattr__(name: str) -> Any:
    """Lazily re-export the plugin-command contract without importing metadata."""
    if name in {"LoadedPluginCommand", "PluginCommandLoadError"}:
        from sase.plugin_commands import adapter

        return getattr(adapter, name)
    if name in {"PluginCommandProblem", "PluginCommandSet"}:
        from sase.plugin_commands import registry

        return getattr(registry, name)
    if name == "PluginCommandRecord":
        from sase.plugin_commands import scan

        return scan.PluginCommandRecord
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
