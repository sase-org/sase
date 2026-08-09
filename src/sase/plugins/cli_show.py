"""Orchestration for ``sase plugin show <plugin_name>``: find, then render or JSON.

Like :mod:`sase.plugins.cli_list`, this is the PatchI-facing seam on top of the
Phase 1 catalog engine. It loads the catalog via
:func:`sase.plugins.catalog.load_plugin_catalog`, resolves the requested plugin
with :func:`sase.plugins.catalog.find_plugin`, and either prints the stable
``-j|--json`` payload or hands the entry to the Rich detail renderer. A miss
yields ranked "did you mean…?" suggestions and a non-zero exit. No GitHub or
cache details leak through here — only the public catalog facade.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from rich.console import Console

from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
    find_plugin,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.json_payload import plugin_entry_json
from sase.plugins.latest import enrich_with_latest
from sase.plugins.render import render_catalog_show, render_show_not_found

LoadFn = Callable[..., PluginCatalog]
EnrichFn = Callable[..., PluginCatalog]

#: Bump when the ``-j|--json`` payload shape changes incompatibly.
SHOW_JSON_SCHEMA_VERSION = 3


def handle_plugin_show_command(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    load_fn: LoadFn = load_plugin_catalog,
    enrich_fn: EnrichFn = enrich_with_latest,
    now: float | None = None,
) -> int:
    """Run ``sase plugin show <plugin_name>``; return the process exit code."""
    query = str(getattr(args, "plugin_name", "") or "")
    offline = bool(getattr(args, "offline", False))
    refresh = bool(getattr(args, "refresh", False))
    as_json = bool(getattr(args, "json", False))
    now = time.time() if now is None else now

    try:
        catalog = load_fn(refresh=refresh, offline=offline)
    except PluginCatalogError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    catalog = _enrich_catalog(
        catalog,
        offline=offline,
        refresh=refresh,
        enrich_fn=enrich_fn,
    )

    entry = find_plugin(catalog, query)
    if entry is None:
        suggestions = suggest_plugins(catalog, query)
        if as_json:
            print(
                json.dumps(
                    _build_not_found_json(catalog, query, suggestions, now=now),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 1
        render_show_not_found(
            query, suggestions, console=console or Console(stderr=True)
        )
        return 1

    if as_json:
        print(
            json.dumps(
                _build_show_json(catalog, entry, query, now=now),
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    render_catalog_show(entry, catalog=catalog, now=now, console=console)
    return 0


def _build_show_json(
    catalog: PluginCatalog,
    entry: PluginCatalogEntry,
    query: str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Build the stable ``sase plugin show --json`` payload for a found plugin."""
    payload = _base_json(catalog, query, now=now)
    payload["found"] = True
    payload["plugin"] = plugin_entry_json(entry)
    return payload


def _build_not_found_json(
    catalog: PluginCatalog,
    query: str,
    suggestions: tuple[PluginCatalogEntry, ...],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Build the stable ``--json`` payload for a miss, with ranked suggestions."""
    payload = _base_json(catalog, query, now=now)
    payload["found"] = False
    payload["plugin"] = None
    payload["suggestions"] = [entry.name for entry in suggestions]
    return payload


def _base_json(
    catalog: PluginCatalog, query: str, *, now: float | None = None
) -> dict[str, Any]:
    now = time.time() if now is None else now
    return {
        "schema_version": SHOW_JSON_SCHEMA_VERSION,
        "query": query,
        "fetched_at": catalog.fetched_at,
        "from_cache": catalog.from_cache,
        "stale": catalog.stale,
        "cache_age_seconds": catalog.age_seconds(now),
        "warnings": list(catalog.warnings),
    }


def _enrich_catalog(
    catalog: PluginCatalog,
    *,
    offline: bool,
    refresh: bool,
    enrich_fn: EnrichFn,
) -> PluginCatalog:
    try:
        return enrich_fn(catalog, offline=offline, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - show stays read-only and best-effort.
        warning = f"could not check plugin updates ({exc})"
        return dataclasses.replace(catalog, warnings=(*catalog.warnings, warning))


__all__ = ["SHOW_JSON_SCHEMA_VERSION", "handle_plugin_show_command"]
