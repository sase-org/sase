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


def sase_json_workflow() -> NoReturn:
    _exec_script("sase_json_workflow")


def sase_migrate_statuses() -> NoReturn:
    _exec_script("sase_migrate_statuses")


def sase_bug() -> NoReturn:
    _exec_script("sase_bug")


def sase_xcmd() -> NoReturn:
    _exec_script("sase_xcmd")


def sase_chop_hook_checks() -> None:
    from sase.scripts.sase_chop_hook_checks import main

    main()


def sase_chop_mentor_checks() -> None:
    from sase.scripts.sase_chop_mentor_checks import main

    main()


def sase_chop_workflow_checks() -> None:
    from sase.scripts.sase_chop_workflow_checks import main

    main()


def sase_chop_pending_checks_poll() -> None:
    from sase.scripts.sase_chop_pending_checks_poll import main

    main()


def sase_chop_comment_zombie_checks() -> None:
    from sase.scripts.sase_chop_comment_zombie_checks import main

    main()


def sase_chop_suffix_transforms() -> None:
    from sase.scripts.sase_chop_suffix_transforms import main

    main()


def sase_chop_orphan_cleanup() -> None:
    from sase.scripts.sase_chop_orphan_cleanup import main

    main()


def sase_chop_stale_running_cleanup() -> None:
    from sase.scripts.sase_chop_stale_running_cleanup import main

    main()


def sase_chop_wait_checks() -> None:
    from sase.scripts.sase_chop_wait_checks import main

    main()


def sase_chop_cl_submitted_checks() -> None:
    from sase.scripts.sase_chop_cl_submitted_checks import main

    main()


def sase_chop_comment_checks() -> None:
    from sase.scripts.sase_chop_comment_checks import main

    main()


def sase_chop_error_digest() -> None:
    from sase.scripts.sase_chop_error_digest import main

    main()
