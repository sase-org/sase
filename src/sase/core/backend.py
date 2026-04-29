"""Backend selection for the sase.core facade.

The Phase 0 plan introduces a stable Python seam (`sase.core`) that future Rust
bindings will replace one operation at a time. Selection is driven by env vars:

- ``SASE_CORE_BACKEND``: ``python`` (default) or ``rust``.
- ``SASE_CORE_DUAL_RUN``: when truthy, run both implementations on dispatched
  operations and log mismatches to ``~/.sase/perf/core_dual_run.jsonl`` (see
  :mod:`sase.core.dual_run`). The dispatcher always returns the Python result
  while dual-run is enabled.

Phase 0A ships only the Python implementation. Selecting the Rust backend
without Rust available raises :class:`RustBackendUnavailableError` rather than
silently falling back; that protects future rollouts from a quiet regression
when the wheel is missing.

Phase 1D introduces the optional ``sase_core_rs`` PyO3 extension module.
:func:`is_rust_available` lazy-imports it so a missing wheel never breaks
startup, and the per-operation facade (currently
:func:`sase.core.parser_facade.parse_project_bytes`) registers a
``rust_impl`` only when the import succeeds.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from enum import StrEnum

RUST_EXTENSION_MODULE_NAME = "sase_core_rs"


# pyvision: tests/test_core_backend.py
class Backend(StrEnum):
    """Selected backend for sase.core dispatched operations."""

    PYTHON = "python"
    RUST = "rust"


DEFAULT_BACKEND = Backend.PYTHON

BACKEND_ENV_VAR = "SASE_CORE_BACKEND"
DUAL_RUN_ENV_VAR = "SASE_CORE_DUAL_RUN"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


# pyvision: tests/test_core_backend.py
class RustBackendUnavailableError(RuntimeError):
    """Raised when the Rust backend is requested but no Rust impl is registered."""


# pyvision: tests/test_core_backend.py
def get_active_backend() -> Backend:
    """Return the backend selected by ``SASE_CORE_BACKEND`` (default python).

    Raises:
        ValueError: if the env var is set to an unknown value.
    """
    raw = os.environ.get(BACKEND_ENV_VAR)
    if raw is None or raw == "":
        return DEFAULT_BACKEND
    normalized = raw.strip().lower()
    if normalized == Backend.PYTHON.value:
        return Backend.PYTHON
    if normalized == Backend.RUST.value:
        return Backend.RUST
    raise ValueError(f"Invalid {BACKEND_ENV_VAR}={raw!r}; expected 'python' or 'rust'.")


# pyvision: tests/test_core_backend.py
def is_dual_run_enabled() -> bool:
    """Return True when ``SASE_CORE_DUAL_RUN`` is set to a truthy value."""
    raw = os.environ.get(DUAL_RUN_ENV_VAR, "")
    return raw.strip().lower() in _TRUTHY


# pyvision: tests/test_core_backend.py
def is_rust_available() -> bool:
    """Return True when the optional ``sase_core_rs`` extension is importable.

    The probe is intentionally lazy and forgiving: any ``ImportError`` (the
    wheel is not installed) returns ``False`` so a pure-Python install is
    never broken by a missing Rust extension. Other import-time failures
    propagate so a misbuilt wheel does not silently disable the Rust
    backend.
    """
    try:
        importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    except ImportError:
        return False
    return True


def load_rust_extension() -> object | None:
    """Return the imported Rust extension module, or ``None`` if missing.

    Centralizes the import so callers (the facade modules) share one
    definition of "the Rust extension" and never branch on the module name
    in their own code.
    """
    try:
        return importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    except ImportError:
        return None


def dispatch[T](
    operation: str,
    *,
    python_impl: Callable[..., T],
    rust_impl: Callable[..., T] | None = None,
    args: tuple = (),
    kwargs: dict | None = None,
    source_path: str | None = None,
) -> T:
    """Run ``operation`` against the active backend.

    The Python implementation is the only required argument. ``rust_impl`` is
    optional and ignored entirely when the Rust backend is not selected and
    dual-run is disabled.

    Behavior:
      - ``SASE_CORE_BACKEND=python`` (default), no dual-run: call ``python_impl``.
      - ``SASE_CORE_BACKEND=python`` with ``SASE_CORE_DUAL_RUN=1`` and a
        ``rust_impl``: call both, log a comparison record, return the Python
        result. With no ``rust_impl`` available, dual-run is a no-op.
      - ``SASE_CORE_BACKEND=rust`` with no ``rust_impl``: raise
        :class:`RustBackendUnavailableError`.
      - ``SASE_CORE_BACKEND=rust`` with ``rust_impl``: call ``rust_impl`` (and
        compare to Python under dual-run, returning the Python result so
        TUI/CLI behavior cannot drift).
    """
    call_kwargs = kwargs or {}
    backend = get_active_backend()

    if backend is Backend.RUST and rust_impl is None:
        raise RustBackendUnavailableError(
            f"Rust backend requested for {operation!r} but no Rust implementation "
            "is registered (Phase 0A ships Python only). Unset "
            f"{BACKEND_ENV_VAR} or install the optional sase_core_rs extension."
        )

    if rust_impl is not None and is_dual_run_enabled():
        from sase.core.dual_run import run_with_comparison

        return run_with_comparison(
            operation=operation,
            python_impl=python_impl,
            rust_impl=rust_impl,
            args=args,
            kwargs=call_kwargs,
            source_path=source_path,
        )

    if backend is Backend.RUST:
        assert rust_impl is not None  # narrowed above
        return rust_impl(*args, **call_kwargs)

    return python_impl(*args, **call_kwargs)
