"""Detect whether the running ``sase`` is managed by ``uv tool``.

``sase update`` / ``sase plugin install`` / ``sase plugin update`` all delegate to
``uv tool``; they are only safe to run when ``sase`` was installed via
``uv tool install sase`` (the canonical install path). This module answers that
question with a **pure** predicate over injected environment probes, so it is
fully unit-testable without touching a real install.

The litmus test (epic decision *D4*): "installed via uv tool" holds iff

1. the ``uv`` binary is on ``PATH``, **and**
2. the running interpreter's ``sys.prefix`` resolves to ``<uv-tool-dir>/sase``,
   **and**
3. that directory contains a ``uv-receipt.toml``.

Anything else (pip / pipx / system, or running from a dev checkout's ``.venv``)
is *not* a uv-tool install. The failure carries a structured
:class:`NotUvToolReason` so the caller can render a precise, actionable message
(uv missing vs. wrong prefix vs. missing receipt).
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: The primary package / uv tool name. ``uv tool install sase`` creates a venv at
#: ``<uv-tool-dir>/sase`` and records the receipt there.
SASE_PACKAGE = "sase"

#: The uv tool receipt filename living in each tool's venv directory.
RECEIPT_FILENAME = "uv-receipt.toml"

WhichFn = Callable[[str], str | None]


class NotUvToolReason(Enum):
    """Why a running interpreter is *not* a managed ``uv tool`` install."""

    #: The ``uv`` binary is not on ``PATH``.
    UV_MISSING = "uv-missing"
    #: ``sys.prefix`` does not resolve to ``<uv-tool-dir>/sase`` (pip/pipx/dev venv).
    WRONG_PREFIX = "wrong-prefix"
    #: The expected ``uv-receipt.toml`` is absent (incomplete/foreign install).
    NO_RECEIPT = "no-receipt"


@dataclass(frozen=True)
class UvToolInstall:
    """A confirmed ``uv tool install sase`` environment."""

    uv_path: str
    tool_dir: Path
    sase_dir: Path
    receipt_path: Path


@dataclass(frozen=True)
class NotUvToolInstall:
    """A negative detection result, carrying the reason and probe context."""

    reason: NotUvToolReason
    sys_prefix: Path
    expected_sase_dir: Path
    receipt_path: Path
    uv_path: str | None = None


def detect_uv_tool_install(
    *,
    which_uv: str | None,
    tool_dir: str | os.PathLike[str],
    sys_prefix: str | os.PathLike[str],
    receipt_exists: bool,
) -> UvToolInstall | NotUvToolInstall:
    """Classify an install from injected probes (pure; no filesystem access).

    *which_uv* is the resolved ``uv`` path (or ``None``), *tool_dir* is the uv
    tool directory (``uv tool dir``), *sys_prefix* is the running interpreter's
    prefix, and *receipt_exists* says whether ``<tool_dir>/sase/uv-receipt.toml``
    is present. Returns :class:`UvToolInstall` on success, otherwise a
    :class:`NotUvToolInstall` carrying the first failing reason.
    """
    tool_dir_path = Path(tool_dir)
    sase_dir = tool_dir_path / SASE_PACKAGE
    receipt_path = sase_dir / RECEIPT_FILENAME
    prefix = Path(sys_prefix)

    def _negative(reason: NotUvToolReason) -> NotUvToolInstall:
        return NotUvToolInstall(
            reason=reason,
            sys_prefix=prefix,
            expected_sase_dir=sase_dir,
            receipt_path=receipt_path,
            uv_path=which_uv,
        )

    if not which_uv:
        return _negative(NotUvToolReason.UV_MISSING)
    if _normalize(prefix) != _normalize(sase_dir):
        return _negative(NotUvToolReason.WRONG_PREFIX)
    if not receipt_exists:
        return _negative(NotUvToolReason.NO_RECEIPT)

    return UvToolInstall(
        uv_path=which_uv,
        tool_dir=tool_dir_path,
        sase_dir=sase_dir,
        receipt_path=receipt_path,
    )


def probe_uv_tool_install(
    *,
    which_fn: WhichFn = shutil.which,
    environ: Mapping[str, str] | None = None,
    sys_prefix: str | os.PathLike[str] | None = None,
) -> UvToolInstall | NotUvToolInstall:
    """Gather the real environment probes and run :func:`detect_uv_tool_install`.

    The thin impure wrapper Phases 2 & 3 call: it resolves ``uv`` on ``PATH``,
    the uv tool directory (``$UV_TOOL_DIR`` or the XDG default), the running
    interpreter prefix, and whether the receipt exists, then delegates to the
    pure predicate.
    """
    env = os.environ if environ is None else environ
    prefix = Path(sys.prefix if sys_prefix is None else sys_prefix)
    tool_dir = default_uv_tool_dir(env)
    receipt_path = sase_receipt_path(tool_dir)
    return detect_uv_tool_install(
        which_uv=which_fn("uv"),
        tool_dir=tool_dir,
        sys_prefix=prefix,
        receipt_exists=receipt_path.is_file(),
    )


def default_uv_tool_dir(environ: Mapping[str, str]) -> Path:
    """Return the uv tool directory, honoring ``$UV_TOOL_DIR`` then XDG defaults.

    Mirrors uv's own resolution: ``$UV_TOOL_DIR`` wins; otherwise
    ``$XDG_DATA_HOME/uv/tools`` (default ``~/.local/share/uv/tools``).
    """
    override = environ.get("UV_TOOL_DIR")
    if override:
        return Path(override)
    xdg = environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "uv" / "tools"


def sase_receipt_path(tool_dir: str | os.PathLike[str]) -> Path:
    """Return the path to ``sase``'s ``uv-receipt.toml`` under *tool_dir*."""
    return Path(tool_dir) / SASE_PACKAGE / RECEIPT_FILENAME


def _normalize(path: Path) -> Path:
    """Lexically normalize a path (no filesystem / symlink resolution)."""
    return Path(os.path.normpath(path))


__all__ = [
    "RECEIPT_FILENAME",
    "SASE_PACKAGE",
    "NotUvToolInstall",
    "NotUvToolReason",
    "UvToolInstall",
    "default_uv_tool_dir",
    "detect_uv_tool_install",
    "probe_uv_tool_install",
    "sase_receipt_path",
]
