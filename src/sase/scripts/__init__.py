"""Bundled scripts that get installed to PATH via pip/uv.

Public API:
    get_script_path(name) -> Path to a bundled script
    run_script(name, args, **kwargs) -> subprocess.CompletedProcess

Adding a new script:
    Python: add module with main(), register in [project.scripts]
    Shell:  add file with shebang, add _exec_script wrapper here,
            register wrapper in [project.scripts]
"""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn


def get_script_path(name: str) -> Path:
    """Return the filesystem path to a bundled script by name.

    Works in both editable and regular installs via importlib.resources.
    """
    ref = files("sase.scripts").joinpath(name)
    return Path(str(ref))


def run_script(
    name: str,
    args: list[str] | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Locate a bundled script and run it via subprocess.

    The interpreter is auto-detected from the shebang line:
    - ``#!/usr/bin/env bash`` (or similar) → ``bash``
    - anything else (or no shebang) → ``sys.executable``

    Extra *kwargs* are forwarded to :func:`subprocess.run`.
    """
    script = get_script_path(name)
    interpreter = _detect_interpreter(script)
    cmd = [interpreter, str(script), *(args or [])]
    kwargs.setdefault("check", True)
    return subprocess.run(cmd, **kwargs)


def _exec_script(name: str) -> NoReturn:
    """Replace the current process with a bundled script.

    Used by thin wrapper functions registered as ``[project.scripts]``
    entry points for shell scripts.
    """
    script = get_script_path(name)
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
