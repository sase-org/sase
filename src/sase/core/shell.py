"""Shell command execution utilities."""

import subprocess
from pathlib import Path


def get_vendored_tool(name: str) -> str:
    """Get the path to a vendored tool script in tools/{name}-YYMMDD.

    Searches the repo's tools/ directory for date-stamped versions of the
    named script. Falls back to the bare name (assumed on PATH) if not found.
    """
    # src/sase/core/shell.py -> src/sase/core -> src/sase -> src -> repo_root
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
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
