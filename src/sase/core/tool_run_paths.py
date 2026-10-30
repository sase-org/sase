"""Machine-local ToolRun store paths.

Split from :mod:`sase.core.tool_run` to keep every file under the 500-line
cap. This module owns ``tools_dir`` and ``tool_run_store_path``; sibling
``tool_run_*`` modules import the public ``tool_run_store_path`` for their
store defaults instead of touching a ``_``-prefixed name across files.
"""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_home

_STORE_FILENAME = "runs.sqlite"


def tools_dir() -> Path:
    """Return the machine-local ToolRun root ``sase_home()/tools``."""

    return sase_home() / "tools"


def tool_run_store_path() -> Path:
    """Return the SQLite path Rust receives for the ToolRun ledger."""

    return tools_dir() / _STORE_FILENAME


__all__ = [
    "tool_run_store_path",
    "tools_dir",
]
