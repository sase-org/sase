"""PEP 562 helpers for package-level lazy re-exports."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any

LazyExportMap = Mapping[str, tuple[str, str]]


def lazy_getattr(
    package_name: str,
    module_globals: dict[str, Any],
    exports: LazyExportMap,
    name: str,
) -> Any:
    """Resolve and cache one package-level lazy export."""
    target = exports.get(name)
    if target is None:
        raise AttributeError(f"module {package_name!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(import_module(module_name), attr_name)
    module_globals[name] = value
    return value


def lazy_dir(module_globals: Mapping[str, Any], exports: LazyExportMap) -> list[str]:
    """Return deterministic ``dir(package)`` output for lazy facades."""
    return sorted({*module_globals, *exports})


__all__ = ["LazyExportMap", "lazy_dir", "lazy_getattr"]
