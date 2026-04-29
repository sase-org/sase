"""Strict Rust extension loader for ``sase.core`` facades.

Phase 8A foundation. Unlike :mod:`sase.core.backend`'s legacy
``load_rust_extension`` / ``is_rust_available`` pair, the helpers here do not
inspect ``SASE_CORE_BACKEND``, do not return ``None`` for a missing wheel,
and do not silently fall back to Python. The contract is:

- :func:`require_rust_extension` imports ``sase_core_rs`` and returns the
  module. A missing or unimportable wheel raises :class:`ImportError` whose
  message names the package and the supported install commands. Other
  import-time errors (e.g. an ABI mismatch) propagate verbatim, matching the
  legacy probe's "broken wheel surfaces, missing wheel does not" split.
- :func:`require_rust_binding` looks up a single named attribute on the
  Rust extension and returns it. Importing the extension is delegated to
  :func:`require_rust_extension`; a missing attribute raises
  :class:`AttributeError` with operation-specific text so a stale wheel
  fails with a clear pointer at the call site instead of one generic error.

These helpers are the only supported import path for ported facades after
Phase 8 deletes :func:`sase.core.backend.dispatch`. See
``plans/202604/rust_backend_phase8.md`` for the migration plan.
"""

from __future__ import annotations

import importlib
from typing import Any

RUST_EXTENSION_MODULE_NAME = "sase_core_rs"

_INSTALL_HINT = (
    "reinstall with `just install` (or `just rust-install` for an editable "
    "build against ../sase-core)"
)


# pyvision: tests/test_core_rust.py
def require_rust_extension() -> Any:
    """Import and return the ``sase_core_rs`` extension module.

    Raises:
        ImportError: when the wheel is not importable in this environment.
            The error message names the package and the supported install
            commands. Non-``ImportError`` import-time failures propagate
            verbatim so a misbuilt or ABI-incompatible wheel surfaces
            instead of looking like a missing install.
    """
    try:
        return importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    except ImportError as exc:
        raise ImportError(
            f"{RUST_EXTENSION_MODULE_NAME} is not importable in this "
            f"environment but is a hard runtime dependency of sase; "
            f"{_INSTALL_HINT}."
        ) from exc


# pyvision: tests/test_core_rust.py
def require_rust_binding(name: str) -> Any:
    """Return ``sase_core_rs.<name>`` or raise with operation-specific text.

    Raises:
        ImportError: when the extension module itself is not importable
            (delegated to :func:`require_rust_extension`).
        AttributeError: when the extension is importable but does not
            expose the requested binding. This typically means the wheel
            is too old or was built without the shipped Phase 8 bindings.
    """
    module = require_rust_extension()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(
            f"{RUST_EXTENSION_MODULE_NAME} is importable but does not expose "
            f"binding {name!r}; the installed wheel is stale or was built "
            f"without the shipped Phase 8 bindings. {_INSTALL_HINT.capitalize()}."
        ) from exc
