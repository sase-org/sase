"""Orchestration for ``sase plugin list``: load, then render or emit JSON.

This is the CLI-facing seam on top of the Phase 1 catalog engine. It loads the
catalog via :func:`sase.plugins.catalog.load_plugin_catalog`, then either prints
the stable ``-j|--json`` payload or hands the model to the Rich renderer. No
GitHub or cache details leak through here — only the public catalog facade.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogError,
    load_plugin_catalog,
)
from sase.plugins.json_payload import plugin_entry_json
from sase.plugins.render import render_catalog_list

LoadFn = Callable[..., PluginCatalog]

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
LIST_JSON_SCHEMA_VERSION = 1


def handle_plugin_list_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    now: float | None = None,
) -> int:
    """Run ``sase plugin list``; return the process exit code."""
    refresh = bool(getattr(args, "refresh", False))
    verbose = bool(getattr(args, "verbose", False))
    as_json = bool(getattr(args, "json", False))
    now = time.time() if now is None else now

    try:
        catalog = load_fn(refresh=refresh)
    except PluginCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(_build_list_json(catalog, now=now), indent=2, sort_keys=True))
        return 0

    render_catalog_list(catalog, verbose=verbose, now=now, console=console)
    return 0


def _build_list_json(
    catalog: PluginCatalog, *, now: float | None = None
) -> dict[str, Any]:
    """Build the stable ``sase plugin list --json`` payload."""
    now = time.time() if now is None else now
    return {
        "schema_version": LIST_JSON_SCHEMA_VERSION,
        "query": catalog.query,
        "fetched_at": catalog.fetched_at,
        "from_cache": catalog.from_cache,
        "stale": catalog.stale,
        "cache_age_seconds": catalog.age_seconds(now),
        "warnings": list(catalog.warnings),
        "counts": {
            "builtin": len(catalog.builtin_entries),
            "community": len(catalog.community_entries),
            "installed": catalog.installed_count,
            "total": len(catalog.entries),
        },
        "entries": [plugin_entry_json(entry) for entry in catalog.entries],
    }


__all__ = ["LIST_JSON_SCHEMA_VERSION", "handle_plugin_list_command"]
