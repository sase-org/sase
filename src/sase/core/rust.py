"""Strict Rust extension loader for ``sase.core`` facades.

The helpers here do not inspect any env var, do not return ``None`` for a
missing wheel, and do not silently fall back to Python. They are the only
supported import path for ported facades. Contract:

- :func:`require_rust_extension` imports ``sase_core_rs`` and returns the
  module. A missing or unimportable wheel raises :class:`ImportError` whose
  message names the package and the supported install commands. Other
  import-time errors (e.g. an ABI mismatch) propagate verbatim so a broken
  wheel surfaces clearly instead of looking like a missing install.
- :func:`require_rust_binding` looks up a single named attribute on the
  Rust extension and returns it. Importing the extension is delegated to
  :func:`require_rust_extension`; a missing attribute raises
  :class:`AttributeError` with operation-specific text so a stale wheel
  fails with a clear pointer at the call site instead of one generic error.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

RUST_EXTENSION_MODULE_NAME = "sase_core_rs"

_PROJECT_INSTALL_HINT = (
    "reinstall with `just install` (or `just rust-install` for an editable "
    "build against ../sase-core)"
)


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
            f"{_install_hint()}."
        ) from exc


def require_rust_binding(name: str) -> Any:
    """Return ``sase_core_rs.<name>`` or raise with operation-specific text.

    Raises:
        ImportError: when the extension module itself is not importable
            (delegated to :func:`require_rust_extension`).
        AttributeError: when the extension is importable but does not
            expose the requested binding. This typically means the wheel
            is too old or was built without the shipped bindings.
    """
    module = require_rust_extension()
    try:
        return getattr(module, name)
    except AttributeError as exc:
        raise AttributeError(
            f"{RUST_EXTENSION_MODULE_NAME} is importable but does not expose "
            f"binding {name!r}; the installed wheel is stale or was built "
            f"without the shipped bindings. {_install_hint().capitalize()}."
        ) from exc


def _install_hint() -> str:
    if _is_uv_tool_context():
        python = _venv_python(Path(sys.prefix))
        return (
            "repair the uv-tool venv with "
            f'`uv pip install --python "{python}" --force-reinstall '
            "sase-core-rs` (or reinstall the tool with "
            "`uv tool install --force sase`)"
        )
    return _PROJECT_INSTALL_HINT


def _is_uv_tool_context() -> bool:
    try:
        prefix = _normalize(Path(sys.prefix))
        expected = _normalize(_default_uv_tool_dir() / "sase")
    except (OSError, RuntimeError, ValueError):
        return False
    return prefix == expected


def _default_uv_tool_dir() -> Path:
    override = os.environ.get("UV_TOOL_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "uv" / "tools"


def _normalize(path: Path) -> Path:
    return Path(os.path.normpath(os.fspath(path.expanduser())))


def _venv_python(prefix: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return prefix / scripts_dir / executable
