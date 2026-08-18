"""Shared ``<plugin>@<id>`` parsing for every ``use:`` config consumer."""

from __future__ import annotations

import re

#: The literal plugin prefix for a provider or spec that ships with sase itself.
_BUILTIN_PLUGIN_PREFIX = "builtin"

_QUALIFIED_ID_RE = re.compile(
    r"^(?P<plugin>[A-Za-z0-9._-]+)@(?P<id>[a-z0-9][a-z0-9_-]*)$"
)


class PluginQualifiedIdError(ValueError):
    """Raised when a ``use:`` value is not a valid ``<plugin>@<id>`` reference."""


def parse_plugin_qualified_id(value: str) -> tuple[str, str]:
    """Parse a ``use:`` value into its ``(plugin, id)`` parts.

    *value* must be exactly ``<plugin>@<id>``, where ``<plugin>`` is the
    literal ``builtin`` or an installed distribution name and ``<id>`` is the
    provider or spec id. Raises :class:`PluginQualifiedIdError` naming the
    required shape otherwise.
    """
    match = _QUALIFIED_ID_RE.fullmatch(value)
    if match is None:
        raise PluginQualifiedIdError(
            f"{value!r} is missing its required plugin prefix; use "
            "'<plugin>@<id>' where <plugin> is 'builtin' or an installed "
            "distribution name"
        )
    return match.group("plugin"), match.group("id")


def plugin_qualified_id_matches(plugin: str, *, builtin: bool, package: str) -> bool:
    """Return whether a resolved provider satisfies a declared *plugin* prefix."""
    if plugin == _BUILTIN_PLUGIN_PREFIX:
        return builtin
    return not builtin and package == plugin


__all__ = [
    "PluginQualifiedIdError",
    "parse_plugin_qualified_id",
    "plugin_qualified_id_matches",
]
