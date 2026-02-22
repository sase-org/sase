"""Discovery and execution of external chop scripts.

Chop scripts are standalone executables that implement chop logic
outside the Python process.  They are discovered by name in configured
directories or on ``$PATH`` (with a ``sase_chop_`` prefix).
"""

import os
import shutil
import subprocess
from pathlib import Path


def discover_chop_script(name: str, search_dirs: list[str]) -> Path | None:
    """Find an executable chop script by name.

    Searches *search_dirs* for an executable file matching *name*,
    then falls back to ``shutil.which("sase_chop_<name>")``.

    Args:
        name: Chop name to look up.
        search_dirs: Directories to search (in order).

    Returns:
        Path to the executable, or ``None`` if not found.
    """
    for d in search_dirs:
        candidate = Path(d) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    # Fallback: look for sase_chop_<name> on PATH
    on_path = shutil.which(f"sase_chop_{name}")
    if on_path is not None:
        return Path(on_path)

    return None


def run_chop_script(
    script_path: Path,
    context_file: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a chop script with the given context file.

    Args:
        script_path: Path to the executable script.
        context_file: Path to the JSON context file.
        timeout: Optional timeout in seconds.

    Returns:
        The completed process result.
    """
    return subprocess.run(
        [str(script_path), "--context", str(context_file)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def list_chop_scripts(search_dirs: list[str]) -> list[str]:
    """List all available chop scripts.

    Scans *search_dirs* for executables and ``$PATH`` for executables
    prefixed with ``sase_chop_``.  Deduplicates and returns sorted
    names.

    Args:
        search_dirs: Directories to scan.

    Returns:
        Sorted list of unique chop script names.
    """
    names: set[str] = set()

    # Scan configured directories
    for d in search_dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            if entry.is_file() and os.access(entry, os.X_OK):
                names.add(entry.name)

    # Scan PATH for sase_chop_* executables
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            try:
                is_file = entry.is_file()
            except OSError:
                continue
            if (
                is_file
                and entry.name.startswith("sase_chop_")
                and os.access(entry, os.X_OK)
            ):
                # Strip the sase_chop_ prefix
                names.add(entry.name[len("sase_chop_") :])

    return sorted(names)
