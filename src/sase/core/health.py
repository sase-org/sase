"""Backend health check for the optional ``sase_core_rs`` extension.

Phase 6D introduces a single scriptable answer to the question "is the Rust
core active and healthy?". The check is intentionally cheap and does not rely
on a dispatched binding to surface module path / version / selected backend —
that distinguishes it from invoking a facade and watching for a failure.

Behavior summary:

- Default Rust (or explicit ``SASE_CORE_BACKEND=rust``) requires
  ``sase_core_rs`` to import; if the import fails or the import succeeds but
  ``parse_query`` is missing/broken, the result is ``status="error"`` and the
  CLI exit code is non-zero.
- Explicit ``SASE_CORE_BACKEND=python`` reports ``status="ok"`` even when
  ``sase_core_rs`` is missing — Python mode is the documented escape hatch
  through Phase 7.
- Misbuilt extension import failures (anything other than ``ImportError``)
  are surfaced verbatim: this matches :func:`sase.core.backend.is_rust_available`,
  which deliberately lets non-``ImportError`` import errors propagate so a
  broken wheel does not silently disable the Rust backend.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from sase.core.backend import (
    BACKEND_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    Backend,
    get_active_backend,
    is_dual_run_enabled,
    load_rust_extension,
)

HEALTH_OK = "ok"
HEALTH_ERROR = "error"

_HEALTH_PROBE_QUERY = "status:Ready"


@dataclass(frozen=True)
class BackendHealthReport:
    """Result of :func:`check_backend_health`.

    The dataclass is frozen so callers cannot accidentally mutate the
    JSON-shaped report between collection and serialization.
    """

    status: str
    backend: str
    dual_run: bool
    rust_required: bool
    rust_extension_module: str
    rust_extension_loaded: bool
    rust_extension_path: str | None
    rust_extension_version: str | None
    python_version: str
    platform: str
    probe_query: str
    probe_ok: bool
    error: str | None = None
    error_kind: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return asdict(self)


def _module_version(module: object) -> str | None:
    """Return ``module.__version__`` if exposed, else ``None``.

    PyO3 extensions don't always set ``__version__``; this is best-effort and
    safe to call on a real or fake module.
    """
    return getattr(module, "__version__", None)


def _module_path(module: object) -> str | None:
    """Return ``module.__file__`` if available, else ``None``.

    Built-in or namespace-style modules may omit ``__file__``.
    """
    return getattr(module, "__file__", None)


def check_backend_health() -> BackendHealthReport:
    """Run a cheap end-to-end check of the active backend.

    Steps:

    1. Resolve the selected backend (``SASE_CORE_BACKEND``) and dual-run flag.
    2. Try to import ``sase_core_rs``.
    3. Call a single shipped binding (``parse_query("status:Ready")``) when
       Rust is required or the extension is loaded; this is the same probe
       documented in Phase 6A's wheel smoke and Phase 6B's install smoke.

    Rust is "required" when the active backend is Rust. In that case a
    missing or broken ``sase_core_rs`` is reported as ``status="error"``.
    Under explicit Python mode the same import failure is non-fatal.
    """
    backend = get_active_backend()
    dual_run = is_dual_run_enabled()
    rust_required = backend is Backend.RUST

    rust_module: object | None = None
    error: str | None = None
    error_kind: str | None = None

    try:
        rust_module = load_rust_extension()
    except Exception as exc:  # noqa: BLE001 — surface misbuilt-wheel errors verbatim.
        rust_module = None
        error = f"failed to import {RUST_EXTENSION_MODULE_NAME}: {exc}"
        error_kind = type(exc).__name__

    rust_loaded = rust_module is not None

    if rust_required and not rust_loaded and error is None:
        error = (
            f"{RUST_EXTENSION_MODULE_NAME} is not importable in this "
            f"environment, but {BACKEND_ENV_VAR}=rust requires it. "
            f"Install {RUST_EXTENSION_MODULE_NAME} or set "
            f"{BACKEND_ENV_VAR}=python."
        )
        error_kind = "ImportError"

    probe_ok = False
    if rust_loaded and error is None:
        try:
            parse_query = rust_module.parse_query  # type: ignore[attr-defined]
        except AttributeError:
            error = (
                f"{RUST_EXTENSION_MODULE_NAME} is importable but does not "
                "expose parse_query; the extension is too old or was built "
                "without the shipped Phase 6 bindings."
            )
            error_kind = "AttributeError"
        else:
            try:
                parse_query(_HEALTH_PROBE_QUERY)
                probe_ok = True
            except Exception as exc:  # noqa: BLE001 — surface broken wheel.
                error = (
                    f"{RUST_EXTENSION_MODULE_NAME}.parse_query("
                    f"{_HEALTH_PROBE_QUERY!r}) raised {type(exc).__name__}: "
                    f"{exc}"
                )
                error_kind = type(exc).__name__

    if rust_required:
        status = HEALTH_OK if probe_ok and error is None else HEALTH_ERROR
    else:
        status = HEALTH_OK if error is None else HEALTH_ERROR

    return BackendHealthReport(
        status=status,
        backend=backend.value,
        dual_run=dual_run,
        rust_required=rust_required,
        rust_extension_module=RUST_EXTENSION_MODULE_NAME,
        rust_extension_loaded=rust_loaded,
        rust_extension_path=_module_path(rust_module) if rust_loaded else None,
        rust_extension_version=(
            _module_version(rust_module) if rust_loaded else None
        ),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        probe_query=_HEALTH_PROBE_QUERY,
        probe_ok=probe_ok,
        error=error,
        error_kind=error_kind,
    )
