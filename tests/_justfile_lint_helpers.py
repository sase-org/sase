"""Shared helpers for the split justfile-lint test modules.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_justfile_lint_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clean_sase_core_env() -> dict[str, str]:
    """Return the environment with sase-core overrides removed."""
    env = os.environ.copy()
    env.pop("SASE_CORE_DIR", None)
    env.pop("SASE_CORE_WHEEL", None)
    env.pop("SASE_CORE_WHEEL_CACHE_DIR", None)
    env.pop("SASE_ALLOW_STALE_CORE", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_LINKED_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_SASE_CORE_PRIMARY_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_DIR", None)
    env.pop("SASE_SIBLING_REPO_CORE_PRIMARY_DIR", None)
    return env


def dry_run(*args: str) -> str:
    """Return the combined output of a Justfile ``--dry-run`` invocation."""
    result = subprocess.run(
        ["just", "--justfile", str(ROOT / "Justfile"), "--dry-run", *args],
        cwd=ROOT,
        env=clean_sase_core_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def copy_justfile(root: Path) -> None:
    """Copy the repo Justfile into a scratch test root."""
    shutil.copyfile(ROOT / "Justfile", root / "Justfile")
