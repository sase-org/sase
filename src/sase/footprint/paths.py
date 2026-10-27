"""Filesystem locations and effective mode for Footprint.

Stdlib only. The root resolves exactly as ``sase.core.paths.sase_home()``
does (``$SASE_HOME`` or ``~/.sase``); a test pins the two together.
"""

from __future__ import annotations

import os
from pathlib import Path

MODE_OFF = "off"
MODE_LOCAL = "local"
MODE_TEST = "test"


def sase_home() -> Path:
    """Return the SASE state root.

    Mirrors ``sase.core.paths.sase_home`` without importing it, so hot paths
    stay on stdlib plus this module.
    """
    return Path(os.environ.get("SASE_HOME") or Path.home() / ".sase").expanduser()


def footprint_dir() -> Path:
    """Return ``<root>/footprint/`` (directory mode 0700)."""
    return sase_home() / "footprint"


def spool_dir() -> Path:
    """Return ``<root>/footprint/spool/``."""
    return footprint_dir() / "spool"


def ledger_path() -> Path:
    """Return ``<root>/footprint/footprint.sqlite``."""
    return footprint_dir() / "footprint.sqlite"


def mode_path() -> Path:
    """Return ``<root>/footprint/mode``."""
    return footprint_dir() / "mode"


def generation_path() -> Path:
    """Return ``<root>/footprint/generation``."""
    return footprint_dir() / "generation"


def _under_pytest(environ: os._Environ[str] | dict[str, str]) -> bool:
    return "PYTEST_CURRENT_TEST" in environ or "PYTEST_VERSION" in environ


def effective_mode(
    environ: dict[str, str] | None = None,
    mode_file: Path | None = None,
) -> str:
    """Return the effective recording mode: ``off``, ``local``, or ``test``.

    Decided in this order:

    1. ``SASE_FOOTPRINT=off`` means off (benchmarks, demos, user scripts).
    2. Under pytest, off unless ``SASE_FOOTPRINT=test``.
    3. ``SASE_FOOTPRINT=local`` forces local outside pytest.
    4. Otherwise the mode file, which holds ``off`` or ``local``. A missing
       or unreadable file means ``local``.
    """
    env = os.environ if environ is None else environ
    override = env.get("SASE_FOOTPRINT")
    if override == MODE_OFF:
        return MODE_OFF
    if _under_pytest(env):
        return MODE_TEST if override == MODE_TEST else MODE_OFF
    if override == MODE_LOCAL:
        return MODE_LOCAL
    path = mode_file if mode_file is not None else mode_path()
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return MODE_LOCAL
    return MODE_OFF if content == MODE_OFF else MODE_LOCAL


__all__ = [
    "MODE_LOCAL",
    "MODE_OFF",
    "MODE_TEST",
    "effective_mode",
    "footprint_dir",
    "generation_path",
    "ledger_path",
    "mode_path",
    "sase_home",
    "spool_dir",
]
