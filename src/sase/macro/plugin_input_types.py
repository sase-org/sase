"""Plugin-shared enum registry adapter with process-local caching.

Discovery comes from :mod:`sase.main.plugin_discovery`
(:func:`discover_macro_plugin_input_type_files`). Loading and validation
live in ``sase-core`` via the ``load_macro_input_type_registry`` binding.
This module only converts arguments, caches snapshots, and renders.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

_CACHE: dict[tuple[Any, ...], _CachedRegistry] | None = None


@dataclass(frozen=True)
class _CachedRegistry:
    key: tuple[Any, ...]
    registry: dict[str, Any]
    diagnostics: tuple[dict[str, Any], ...]


def _cache_store() -> dict[tuple[Any, ...], _CachedRegistry]:
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
    return _CACHE


def _clear_plugin_input_type_registry_cache() -> None:
    """Clear the process-local plugin input-type registry cache.

    Cache-clear hook for tests and explicit refresh. Used in-file for cache
    eviction; test imports of this private helper are allowed.
    """
    store = _cache_store()
    store.clear()


def _discovery_snapshot(
    files: list[dict[str, str]] | None,
    *,
    accept_legacy: bool | None = None,
) -> tuple[tuple[Any, ...], list[dict[str, str]], bool]:
    from sase.main.plugin_discovery import (
        discover_macro_plugin_distributions,
        discover_macro_plugin_input_type_files,
    )

    # Retired switch kept for compatibility and ignored: retired sources
    # are always accepted.
    _ = accept_legacy
    accept_legacy = True
    if files is None:
        files = discover_macro_plugin_input_type_files(accept_legacy=accept_legacy)
    # Known distributions independently of manifests, for cache identity.
    try:
        known = discover_macro_plugin_distributions(accept_legacy=accept_legacy)
    except Exception:
        known = []
    disabled = (
        os.environ.get("SASE_DISABLE_PLUGINS"),
        os.environ.get("SASE_DISABLE_PLUGIN_MACROS"),
        os.environ.get("SASE_DISABLE_PLUGIN_XPROMPTS"),
    )
    parts: list[tuple[Any, ...]] = []
    for item in sorted(
        files,
        key=lambda entry: (
            str(entry.get("distribution", "")),
            str(entry.get("path", "")),
            str(entry.get("module", "")),
        ),
    ):
        dist = str(item.get("distribution", ""))
        module = str(item.get("module", ""))
        path = str(item.get("path", ""))
        try:
            stat = Path(path).stat()
            signature = (stat.st_mtime_ns, stat.st_size, True)
        except OSError:
            signature = (0, 0, False)
        parts.append((dist, module, path, signature))
    key = (
        bool(accept_legacy),
        disabled,
        tuple(sorted(known, key=str.lower)),
        tuple(parts),
    )
    return key, files, bool(accept_legacy)


def get_plugin_input_type_registry(
    files: list[dict[str, str]] | None = None,
    *,
    accept_legacy: bool | None = None,
) -> dict[str, Any]:
    """Return the cached Rust registry snapshot for discovered manifests.

    The snapshot is a ``{"registry": {...}, "diagnostics": [...]}`` dict as
    returned by the Rust binding. Diagnostics are retained in the cache but
    re-emitted into every active ``collect_macro_load_issues()`` context so
    a prior catalog load never blinds the doctor.
    """
    from sase.macro.load_issues import record_load_issue

    key, files, _ = _discovery_snapshot(files, accept_legacy=accept_legacy)
    store = _cache_store()
    cached = store.get(key)
    if cached is None:
        binding = require_rust_binding("load_macro_input_type_registry")
        # Pass known distributions so manifest-less plugins stay known.
        from sase.main.plugin_discovery import (
            discover_macro_plugin_distributions,
        )

        try:
            known = discover_macro_plugin_distributions(accept_legacy=accept_legacy)
        except Exception:
            known = []
        payload = binding({"files": files, "known_distributions": known})
        registry = payload.get("registry", {})
        diagnostics = tuple(payload.get("diagnostics", []))
        cached = _CachedRegistry(key=key, registry=registry, diagnostics=diagnostics)
        # Keep only the latest snapshot; discovery identity changes invalidate.
        _clear_plugin_input_type_registry_cache()
        store[key] = cached
    for diagnostic in cached.diagnostics:
        message = str(diagnostic.get("message", "invalid input_types.yml"))
        path = str(diagnostic.get("path", ""))
        source = path or str(diagnostic.get("distribution", ""))
        severity = str(diagnostic.get("severity", "error")).lower()
        kind = "input_type_warning" if severity == "warning" else "input_type"
        record_load_issue(source, message, kind=kind)
    return {"registry": cached.registry, "diagnostics": list(cached.diagnostics)}
