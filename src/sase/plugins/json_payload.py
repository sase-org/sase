"""Shared JSON serialization for the ``sase plugin`` CLI payloads.

Both ``sase plugin list`` and ``sase plugin show`` emit the same per-plugin
object shape under ``-j|--json``. This module is the single source of truth for
that shape so the two commands can never drift apart.
"""

from __future__ import annotations

from typing import Any

from sase.plugins.catalog import PluginCatalogEntry


def plugin_entry_json(entry: PluginCatalogEntry) -> dict[str, Any]:
    """Serialize one catalog entry to the stable ``-j|--json`` object shape."""
    return {
        "name": entry.name,
        "repo": entry.repo,
        "full_name": entry.full_name,
        "owner": entry.owner,
        "kind": entry.kind,
        "description": entry.description,
        "url": entry.url,
        "homepage": entry.homepage,
        "topics": list(entry.topics),
        "stars": entry.stars,
        "archived": entry.archived,
        "license": entry.license,
        "updated_at": entry.updated_at,
        "installed": {
            "installed": entry.installed.installed,
            "version": entry.installed.version,
            "entry_point_groups": list(entry.installed.entry_point_groups),
        },
        "latest": {
            "checked": entry.latest.checked,
            "version": entry.latest.version,
            "source": entry.latest.source,
            "update_available": entry.update_available,
            "error": entry.latest.error,
        },
    }


__all__ = ["plugin_entry_json"]
