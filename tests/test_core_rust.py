"""Tests for the strict Rust extension loader (Phase 8A).

The helpers in :mod:`sase.core.rust` are the post-Phase-8 import path for
ported facades. Unlike the legacy ``load_rust_extension`` / ``is_rust_available``
pair, they never silently return ``None`` and do not inspect
``SASE_CORE_BACKEND``.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from sase.core.rust import (
    RUST_EXTENSION_MODULE_NAME,
    require_rust_binding,
    require_rust_extension,
)


def test_require_rust_extension_returns_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    assert require_rust_extension() is fake


def test_require_rust_extension_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing wheel surfaces as :class:`ImportError`, not ``None``.

    The legacy ``load_rust_extension`` swallowed ``ImportError`` and returned
    ``None``. The strict loader re-raises with a message that names the
    package and the supported install commands, so callers cannot accidentally
    silently fall back to Python.
    """
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def _missing(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", _missing)
    with pytest.raises(ImportError) as excinfo:
        require_rust_extension()
    message = str(excinfo.value)
    assert RUST_EXTENSION_MODULE_NAME in message
    assert "just install" in message


def test_require_rust_extension_propagates_non_import_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ABI/build errors propagate verbatim so a broken wheel is not hidden.

    Mirrors :func:`sase.core.backend.is_rust_available`'s contract: any
    import-time failure that is not an ``ImportError`` (e.g. an ``OSError``
    from a misbuilt extension) is surfaced unchanged so the user sees the
    real cause instead of "package not installed".
    """
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def _broken(name: str) -> object:
        raise OSError(f"undefined symbol while loading {name!r}")

    monkeypatch.setattr(importlib, "import_module", _broken)
    with pytest.raises(OSError, match="undefined symbol while loading"):
        require_rust_extension()


def test_require_rust_binding_returns_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.parse_query = lambda raw: {"raw": raw}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    binding = require_rust_binding("parse_query")
    assert binding("status:Ready") == {"raw": "status:Ready"}


def test_require_rust_binding_missing_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale wheel without the requested binding raises with op-specific text."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    with pytest.raises(AttributeError) as excinfo:
        require_rust_binding("parse_query")
    message = str(excinfo.value)
    assert "parse_query" in message
    assert RUST_EXTENSION_MODULE_NAME in message
    assert "stale" in message


def test_require_rust_binding_missing_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding helper delegates the import error path to the loader."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def _missing(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", _missing)
    with pytest.raises(ImportError):
        require_rust_binding("parse_query")
