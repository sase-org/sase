"""Core utility functions shared across sase modules."""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec

_cached_timezone: ZoneInfo | None = None


def get_timezone() -> ZoneInfo:
    """Get the configured timezone, cached after first call.

    Reads the ``timezone`` key from the merged sase config.
    Falls back to ``America/New_York`` if not configured.
    """
    global _cached_timezone
    if _cached_timezone is None:
        from sase.config.core import load_merged_config

        config = load_merged_config()
        tz_name = config.get("timezone", "America/New_York")
        _cached_timezone = ZoneInfo(tz_name)
    return _cached_timezone


def get_sase_tmpdir() -> str | None:
    """Return the SASE temp directory if $SASE_TMPDIR is set, else None.

    When $SASE_TMPDIR is set, the directory is created if it doesn't exist.
    Returning None lets tempfile functions fall back to the system default.
    """
    sase_tmpdir = os.environ.get("SASE_TMPDIR")
    if sase_tmpdir:
        os.makedirs(sase_tmpdir, exist_ok=True)
        return sase_tmpdir
    return None


def get_vendored_tool(name: str) -> str:
    """Get the path to a vendored tool script in tools/{name}-YYMMDD.

    Searches the repo's tools/ directory for date-stamped versions of the
    named script. Falls back to the bare name (assumed on PATH) if not found.
    """
    # src/sase/sase_utils.py -> src/sase -> src -> repo_root
    repo_root = Path(__file__).resolve().parent.parent.parent
    tools_dir = repo_root / "tools"
    if tools_dir.is_dir():
        matches = sorted(tools_dir.glob(f"{name}-*"))
        if matches:
            return str(matches[-1])
    return name


def run_shell_command(
    cmd: str, capture_output: bool = True
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=capture_output,
        text=True,
    )


def generate_timestamp() -> str:
    """Generate a timestamp in YYmmdd_HHMMSS format using the configured timezone.

    Returns:
        Timestamp string like "251227_143052"
    """
    return datetime.now(get_timezone()).strftime("%y%m%d_%H%M%S")


def get_sase_directory(subdir: str) -> str:
    """Get the path to a subdirectory under ~/.sase/.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path like "/home/user/.sase/hooks"
    """
    return os.path.expanduser(f"~/.sase/{subdir}")


def ensure_sase_directory(subdir: str) -> str:
    """Ensure a ~/.sase subdirectory exists and return its path.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path to the created/existing directory
    """
    dir_path = get_sase_directory(subdir)
    Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


def make_safe_filename(name: str) -> str:
    """Convert a string to a safe filename by replacing non-alphanumeric chars.

    Args:
        name: The string to convert

    Returns:
        Safe filename with only alphanumeric chars and underscores
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def strip_reverted_suffix(name: str) -> str:
    """Remove the _<N> suffix from a reverted ChangeSpec name.

    Supports both legacy ``__<N>`` and current ``_<N>`` suffixes.

    Args:
        name: ChangeSpec name (e.g., "foobar_feature_2")

    Returns:
        Name without the suffix (e.g., "foobar_feature")
    """
    # Try legacy double-underscore first to avoid partial matches
    match = re.match(r"^(.+)__\d+$", name)
    if match:
        return match.group(1)
    # Then try single-underscore
    match = re.match(r"^(.+)_\d+$", name)
    return match.group(1) if match else name


def changespec_name_to_branch(name: str, project_basename: str) -> str:
    """Derive the git branch name from a ChangeSpec NAME.

    Strips project prefix and _<N> / __<N> suffix, converts underscores to hyphens.
    Example: changespec_name_to_branch("sase_dull_basin_1", "sase") -> "dull-basin"
    """
    name = strip_reverted_suffix(name)
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return name.replace("_", "-")


def changespec_name_to_branch_with_suffix(name: str, project_basename: str) -> str:
    """Derive git branch name from a ChangeSpec name, preserving the _<N> suffix.

    Like ``changespec_name_to_branch`` but keeps the uniqueness suffix.
    Underscores in the body are converted to hyphens, but the ``_<N>``
    suffix delimiter stays as an underscore.

    Example::

        >>> changespec_name_to_branch_with_suffix("sase_dull_basin_1", "sase")
        'dull-basin_1'
    """
    prefix = f"{project_basename}_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    # Try legacy __<N> first to avoid partial matches
    match = re.match(r"^(.+)__(\d+)$", name)
    if match:
        base = match.group(1).replace("_", "-")
        return f"{base}__{match.group(2)}"
    match = re.match(r"^(.+)_(\d+)$", name)
    if match:
        base = match.group(1).replace("_", "-")
        return f"{base}_{match.group(2)}"
    return name.replace("_", "-")


def has_suffix(name: str) -> bool:
    """Check if a ChangeSpec name has a _<N> or legacy __<N> suffix.

    Args:
        name: ChangeSpec name to check

    Returns:
        True if name has a suffix, False otherwise
    """
    return bool(re.match(r"^.+__\d+$", name) or re.match(r"^.+_\d+$", name))


def get_next_suffix_number(base_name: str, existing_names: set[str]) -> int:
    """Find the lowest positive integer N such that `<base_name>_<N>` doesn't exist.

    Also checks legacy ``__<N>`` names to avoid slot collisions.

    Args:
        base_name: The base name to append suffix to
        existing_names: Set of existing names to check for conflicts

    Returns:
        The lowest available suffix number
    """
    n = 1
    while f"{base_name}_{n}" in existing_names or f"{base_name}__{n}" in existing_names:
        n += 1
    return n


def shorten_path(path: str) -> str:
    """Shorten a file path by replacing home directory with ~.

    Args:
        path: Full file path

    Returns:
        Path with home directory replaced by ~
    """
    return path.replace(str(Path.home()), "~")


def get_workspace_directory_for_changespec(changespec: "ChangeSpec") -> str | None:
    """Get the workspace directory for a ChangeSpec.

    Args:
        changespec: The ChangeSpec to get workspace directory for

    Returns:
        The workspace directory path, or None if not found
    """
    from sase.running_field import get_workspace_directory as get_workspace_dir

    try:
        return get_workspace_dir(changespec.project_basename)
    except RuntimeError:
        return None


def strip_hook_prefix(hook_command: str) -> str:
    """Strip the '!' and '$' prefixes from a hook command if present.

    Prefixes:
    - '!' indicates FAILED status lines should auto-append error suffix
    - '$' indicates the hook should not run for proposal COMMITS entries

    Args:
        hook_command: The hook command string.

    Returns:
        The command with all prefixes stripped.
    """
    return hook_command.lstrip("!$")


def run_workspace_command(
    cmd: list[str], workspace_dir: str, capture_output: bool = True
) -> tuple[bool, str | None]:
    """Run a subprocess command in a workspace directory.

    A generic wrapper for running commands like sase_hg_prune, sase_hg_update,
    sase_hg_archive, hg import, and sase commit in a workspace directory.

    Args:
        cmd: The command and arguments to run.
        workspace_dir: The workspace directory to run the command in.
        capture_output: Whether to capture stdout/stderr.

    Returns:
        Tuple of (success, error_message).
    """
    cmd_name = cmd[0]
    try:
        result = subprocess.run(
            cmd,
            cwd=workspace_dir,
            capture_output=capture_output,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            error_msg = ""
            if capture_output:
                error_msg = result.stderr.strip() or result.stdout.strip()
            return (
                False,
                (
                    f"{cmd_name} failed: {error_msg}"
                    if error_msg
                    else f"{cmd_name} failed"
                ),
            )

        return (True, None)
    except FileNotFoundError:
        return (False, f"{cmd_name} command not found")
    except Exception as e:
        return (False, f"Error running {cmd_name}: {e}")
