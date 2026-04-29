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
"""

from __future__ import annotations

import os
from collections.abc import Callable
from enum import StrEnum


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
    """Return True when a Rust implementation is importable.

    Phase 0A: always ``False``. Phase 1 will probe an optional ``sase_core_rs``
    extension module here.
    """
    return False


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
