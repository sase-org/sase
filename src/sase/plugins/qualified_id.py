"""Shared ``<plugin>@<id>`` parsing for every ``use:`` config consumer."""

from __future__ import annotations

import re

#: The literal plugin prefix for a provider or spec that ships with sase itself.
BUILTIN_PLUGIN_PREFIX = "builtin"
_BUILTIN_PLUGIN_PREFIX = BUILTIN_PLUGIN_PREFIX

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


def canonical_plugin_prefix(plugin: str) -> str:
    """Return the packaging-normalized plugin/distribution prefix.

    ``builtin`` is preserved as the literal builtin prefix, including mixed-case
    spellings. Installed distribution names use PEP 503 canonicalization so
    mixed-case, hyphen, underscore, and dot variants compare equal.
    """

    if plugin.casefold() == BUILTIN_PLUGIN_PREFIX:
        return BUILTIN_PLUGIN_PREFIX
    # Imported lazily: sase.version's package init is not a leaf and would
    # otherwise cycle back through config.file_hooks into this module.
    from sase.version._utils import normalize_distribution_name

    return normalize_distribution_name(plugin)


def canonical_plugin_qualified_id(value: str) -> str:
    """Return ``<plugin>@<id>`` with a packaging-normalized plugin prefix."""

    plugin, spec_id = parse_plugin_qualified_id(value)
    return f"{canonical_plugin_prefix(plugin)}@{spec_id}"


def plugin_qualified_id_matches(plugin: str, *, builtin: bool, package: str) -> bool:
    """Return whether a resolved provider satisfies a declared *plugin* prefix."""
    if plugin.casefold() == _BUILTIN_PLUGIN_PREFIX:
        return builtin
    return not builtin and canonical_plugin_prefix(package) == canonical_plugin_prefix(
        plugin
    )


__all__ = [
    "BUILTIN_PLUGIN_PREFIX",
    "PluginQualifiedIdError",
    "canonical_plugin_prefix",
    "canonical_plugin_qualified_id",
    "parse_plugin_qualified_id",
    "plugin_qualified_id_matches",
]
