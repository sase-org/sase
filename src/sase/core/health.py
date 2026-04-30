"""Core health check for the required ``sase_core_rs`` extension.

The check verifies that the Rust extension is installed and exposes a known
cheap binding (``parse_query``) so release smokes and user scripts can
branch on the exit code without parsing output. ``sase_core_rs`` is a hard
runtime dependency; there is no Python-mode escape hatch.

Behavior summary:

- The extension must import. A missing wheel produces ``status="error"`` and
  the CLI exits non-zero. Non-``ImportError`` import-time failures (e.g. ABI
  mismatch) surface verbatim so a misbuilt wheel does not look like a
  missing install.
- The extension must expose ``parse_query``. The probe calls it with a
  trivial query (``"status:Ready"``); any failure produces ``status="error"``.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from sase.core.rust import RUST_EXTENSION_MODULE_NAME, require_rust_extension

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
    """Run a cheap end-to-end check of the installed Rust core.

    Steps:

    1. Try to import ``sase_core_rs`` via the strict loader.
    2. Call a single shipped binding (``parse_query("status:Ready")``); this
       is the same probe documented in Phase 6A's wheel smoke and Phase 6B's
       install smoke.

    A missing or broken ``sase_core_rs`` is reported as ``status="error"``.
    """
    rust_module: Any = None
    error: str | None = None
    error_kind: str | None = None

    try:
        rust_module = require_rust_extension()
    except Exception as exc:  # noqa: BLE001 — surface misbuilt-wheel errors verbatim.
        rust_module = None
        error = f"failed to import {RUST_EXTENSION_MODULE_NAME}: {exc}"
        error_kind = type(exc).__name__

    rust_loaded = rust_module is not None

    probe_ok = False
    if rust_loaded and error is None:
        try:
            parse_query = rust_module.parse_query
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

    status = HEALTH_OK if probe_ok and error is None else HEALTH_ERROR

    return BackendHealthReport(
        status=status,
        rust_extension_module=RUST_EXTENSION_MODULE_NAME,
        rust_extension_loaded=rust_loaded,
        rust_extension_path=_module_path(rust_module) if rust_loaded else None,
        rust_extension_version=(_module_version(rust_module) if rust_loaded else None),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        probe_query=_HEALTH_PROBE_QUERY,
        probe_ok=probe_ok,
        error=error,
        error_kind=error_kind,
    )
