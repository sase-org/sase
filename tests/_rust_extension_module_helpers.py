"""Shared ``sys.modules`` patching for the ``sase_core_rs`` extension.

Tests that swap or evict the Rust extension must move the compiled
submodule ``sase_core_rs.sase_core_rs`` together with its parent package.
The shipped ``sase_core_rs/__init__.py`` is maturin's star-import template::

    from .sase_core_rs import *

    __doc__ = sase_core_rs.__doc__

Line 3 reads a name the file never binds; it resolves only because
importlib, on the cache-miss path, does
``setattr(parent_package, child_name, child_module)`` into what happens to
be this file's global namespace. Leave the compiled submodule cached while
the parent package is absent or replaced, and any later re-import returns
the submodule from cache, skips that ``setattr``, and raises
``NameError: name 'sase_core_rs' is not defined`` — poisoning every
subsequent import in that process (and, under pytest-xdist, every later
test scheduled onto that worker).

The helpers here patch parent and submodule as a unit through
``monkeypatch``, so the compiled submodule is absent for exactly as long as
the parent is patched and teardown restores both together.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME

RUST_EXTENSION_SUBMODULE_NAME = (
    f"{RUST_EXTENSION_MODULE_NAME}.{RUST_EXTENSION_MODULE_NAME}"
)


def patch_rust_extension(
    monkeypatch: pytest.MonkeyPatch, module: types.ModuleType
) -> types.ModuleType:
    """Install ``module`` as ``sys.modules[sase_core_rs]``, submodule included.

    The compiled submodule is evicted alongside the parent so a re-import
    while ``module`` is installed takes the cache-miss path and rebinds the
    name the package init reads.
    """
    _evict_compiled_submodule(monkeypatch)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, module)
    return module


def install_fake_rust_extension(
    monkeypatch: pytest.MonkeyPatch, **bindings: Any
) -> types.ModuleType:
    """Install a fresh fake ``sase_core_rs`` exposing ``bindings``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    for name, value in bindings.items():
        setattr(fake, name, value)
    return patch_rust_extension(monkeypatch, fake)


def evict_rust_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ``sase_core_rs`` from ``sys.modules``, submodule included."""
    _evict_compiled_submodule(monkeypatch)
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)


def _evict_compiled_submodule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_SUBMODULE_NAME, raising=False)
