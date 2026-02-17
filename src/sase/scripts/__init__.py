"""Bundled scripts that get installed to PATH via pip/uv.

Adding a new script:
    Python: add module with main(), register in [project.scripts]
    Shell:  add file with shebang, add _exec_script wrapper here,
            register wrapper in [project.scripts]
"""

from __future__ import annotations

import os
import sys
from importlib.resources import files
from pathlib import Path
from typing import NoReturn


def _get_script_path(name: str) -> Path:
    """Return the filesystem path to a bundled script by name.

    Works in both editable and regular installs via importlib.resources.
    """
    ref = files("sase.scripts").joinpath(name)
    return Path(str(ref))


def _exec_script(name: str) -> NoReturn:
    """Replace the current process with a bundled script.

    Used by thin wrapper functions registered as ``[project.scripts]``
    entry points for shell scripts.
    """
    script = _get_script_path(name)
    interpreter = _detect_interpreter(script)
    os.execvp(interpreter, [interpreter, str(script), *sys.argv[1:]])


def _detect_interpreter(script: Path) -> str:
    """Read the shebang of *script* and return an interpreter command."""
    try:
        with open(script) as f:
            first_line = f.readline()
    except (OSError, UnicodeDecodeError):
        return sys.executable

    if first_line.startswith("#!") and "bash" in first_line:
        return "bash"
    if first_line.startswith("#!") and "sh" in first_line:
        return "sh"
    return sys.executable


def sase_hg_amend() -> NoReturn:
    _exec_script("sase_hg_amend")


def sase_hg_archive() -> NoReturn:
    _exec_script("sase_hg_archive")


def sase_hg_clean() -> NoReturn:
    _exec_script("sase_hg_clean")


def sase_hg_lint() -> NoReturn:
    _exec_script("sase_hg_lint")


def sase_hg_patch() -> NoReturn:
    _exec_script("sase_hg_patch")


def sase_hg_presubmit() -> NoReturn:
    _exec_script("sase_hg_presubmit")


def sase_hg_prune() -> NoReturn:
    _exec_script("sase_hg_prune")


def sase_hg_rebase() -> NoReturn:
    _exec_script("sase_hg_rebase")


def sase_hg_rename() -> NoReturn:
    _exec_script("sase_hg_rename")


def sase_hg_reword() -> NoReturn:
    _exec_script("sase_hg_reword")


def sase_hg_sync() -> NoReturn:
    _exec_script("sase_hg_sync")


def sase_hg_unamend() -> NoReturn:
    _exec_script("sase_hg_unamend")


def sase_hg_update() -> NoReturn:
    _exec_script("sase_hg_update")


def sase_hg_upload() -> NoReturn:
    _exec_script("sase_hg_upload")
