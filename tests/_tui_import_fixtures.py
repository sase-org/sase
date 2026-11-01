"""Real temporary source packages for the TUI import-footprint tests.

The footprint tests measure genuine fresh-interpreter imports of small source
packages written under ``tmp_path`` instead of fabricating module-name lists.
``budgetpkg`` stands in for ``sase``: ``budgetpkg.app`` is the startup target.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import _tui_import_footprint as footprint  # noqa: E402


PACKAGE = "budgetpkg"
TARGET = f"{PACKAGE}.app"

_MONOLITH_APP = '''\
"""Monolithic app module."""

from __future__ import annotations

import os
import sys

__all__ = ["alpha", "beta"]


def alpha(value: int) -> int:
    """Double the value."""
    return value * 2


def beta(value: int) -> int:
    """Triple the value."""
    return value * 3
'''

_FACADE_APP = '''\
"""Facade re-exporting the split helpers."""

from __future__ import annotations

from ._alpha import alpha
from ._beta import beta

__all__ = ["alpha", "beta"]
'''

_ALPHA = '''\
"""Alpha helper."""

from __future__ import annotations

import os
import sys


def alpha(value: int) -> int:
    """Double the value."""
    return value * 2
'''

_BETA = '''\
"""Beta helper."""

from __future__ import annotations

import os
import sys


def beta(value: int) -> int:
    """Triple the value."""
    return value * 3
'''

MONOLITH_FILES: Mapping[str, str] = {
    f"{PACKAGE}/__init__.py": "",
    f"{PACKAGE}/app.py": _MONOLITH_APP,
}

SPLIT_FILES: Mapping[str, str] = {
    f"{PACKAGE}/__init__.py": "",
    f"{PACKAGE}/app.py": _FACADE_APP,
    f"{PACKAGE}/_alpha.py": _ALPHA,
    f"{PACKAGE}/_beta.py": _BETA,
}


def implementation(count: int, *, prefix: str = "fn") -> str:
    """Return *count* small functions of executable implementation."""
    return "".join(
        f"def {prefix}_{index}(value: int) -> int:\n    return value + {index}\n\n\n"
        for index in range(count)
    )


def write_files(root: Path, files: Mapping[str, str]) -> None:
    """Write *files* (relative path -> text) under *root*."""
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def with_eager_import(files: Mapping[str, str], module: str) -> dict[str, str]:
    """Return *files* whose app module imports ``budgetpkg.<module>`` eagerly."""
    app = f"{PACKAGE}/app.py"
    return {**files, app: files[app] + f"\nfrom . import {module}\n"}


def measure_package(
    root: Path,
    *,
    target: str = TARGET,
    package: str = PACKAGE,
    deferred_modules: Sequence[str] = (),
    cache: footprint.FootprintCache | None = None,
) -> footprint.ImportMeasurement:
    """Import *target* in a fresh interpreter with *root* on ``PYTHONPATH``."""
    return footprint.measure_import(
        target,
        root=package,
        cwd=root,
        extra_paths=[root],
        deferred_modules=deferred_modules,
        cache=cache,
    )
