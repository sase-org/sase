"""Background periodic checks for the axe scheduler (is_cl_submitted, critique_comments).

This module provides non-blocking execution of CL status and comment checks,
following the same pattern as hooks (subprocess.Popen + file-based polling).
"""

import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.time import generate_timestamp
from sase.status_state_machine import transition_changespec_status

from ..changespec import ChangeSpec, CommentEntry, is_plain_suffix
from ..cl_status import is_parent_submitted
from ..comments import (
    get_comments_file_path,
    remove_comment_entry,
    update_changespec_comments_field,
)
from ..sync_cache import update_last_checked

# Type alias for log callback
LogCallback = Callable[[str, str], None]

# Check type - must be defined before constants
CheckType = Literal["cl_submitted", "reviewer_comments"]

# Check type constants
CHECK_TYPE_CL_SUBMITTED: CheckType = "cl_submitted"
CHECK_TYPE_REVIEWER_COMMENTS: CheckType = "reviewer_comments"

# Completion marker (consistent with hooks/workflows)
CHECK_COMPLETE_MARKER = "===CHECK_COMPLETE=== "

# Exit code meanings for critique_comments command
_CRITIQUE_COMMENTS_EXIT_CODES: dict[int, str] = {
    1: "usage error",
    2: "missing dependency",
    3: "invalid CL number",
    4: "RPC failure",
    5: "JSON parsing failure",
}


@dataclass
class _PendingCheck:
    """Represents a pending background check."""

    changespec_name: str
    check_type: CheckType
    timestamp: str
    output_path: str


def _get_checks_directory() -> str:
    """Get the path to the checks output directory (~/.sase/checks/)."""
    return os.path.expanduser("~/.sase/checks")


def _ensure_checks_directory() -> None:
    """Ensure the checks directory exists."""
    checks_dir = _get_checks_directory()
    Path(checks_dir).mkdir(parents=True, exist_ok=True)


def _get_check_output_path(name: str, check_type: CheckType, timestamp: str) -> str:
    """Get the output file path for a check run.

    Args:
        name: The ChangeSpec name.
        check_type: The type of check.
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the check output file.
    """
    _ensure_checks_directory()
    checks_dir = _get_checks_directory()
    # Replace non-alphanumeric chars with underscore for safe filename
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    filename = f"{safe_name}-{check_type}-{timestamp}.txt"
    return os.path.join(checks_dir, filename)


def _extract_change_identifier(cl_url: str | None) -> tuple[str, str] | None:
    """Extract the change identifier and VCS type from a CL/PR URL.

    Delegates to workspace provider plugins via
    :func:`sase.workspace_provider.extract_change_identifier`.

    Args:
        cl_url: The CL URL (``http://cl/123456789``) or GitHub PR URL
            (``https://github.com/user/repo/pull/42``).

    Returns:
        ``(identifier, vcs_type)`` tuple, or None if the URL is invalid or None.
    """
    if not cl_url:
        return None

    from sase.workspace_provider import extract_change_identifier

    return extract_change_identifier(cl_url)


def _start_background_check(
    script_body: str,
    output_path: str,
    workspace_dir: str | None,
) -> bool:
    """Write a wrapper script around *script_body* and launch it in the background.

    The wrapper adds the ``CHECK_COMPLETE_MARKER`` so callers can poll for
    completion.  *script_body* must NOT use ``exit`` — its final ``$?`` is
    captured automatically.

    Returns:
        ``True`` if the process was started, ``False`` on failure.
    """
    wrapper_script = f"""#!/bin/bash
{script_body}
exit_code=$?
echo ""
echo "{CHECK_COMPLETE_MARKER}EXIT_CODE: $exit_code"
# Clean up this wrapper script since the background process is done with it
rm -f "$0"
exit $exit_code
"""

    from sase.core.paths import get_sase_tmpdir

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, dir=get_sase_tmpdir()
    ) as wrapper_file:
        wrapper_file.write(wrapper_script)
        wrapper_path = wrapper_file.name

    os.chmod(wrapper_path, 0o755)

    with open(output_path, "w") as output_file:
        subprocess.Popen(
            [wrapper_path],
            cwd=workspace_dir,
            stdout=output_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return True


def start_cl_submitted_check(
    changespec: ChangeSpec,
    workspace_dir: str | None,
    log: LogCallback,
) -> str | None:
    """Start is_cl_submitted check as a background process.

    Args:
        changespec: The ChangeSpec to check.
        workspace_dir: The workspace directory to run the command in.
        log: Logging callback.

    Returns:
        Update message if check was started, None if failed.
    """
    result = _extract_change_identifier(changespec.cl)
    if not result:
        return None

    identifier, vcs_type = result

    from sase.workspace_provider import generate_submitted_check_script

    script_body = generate_submitted_check_script(identifier, vcs_type)
    if script_body is None:
        return None

    timestamp = generate_timestamp()
    output_path = _get_check_output_path(
        changespec.name, CHECK_TYPE_CL_SUBMITTED, timestamp
    )

    try:
        _start_background_check(script_body, output_path, workspace_dir)
        return "Started cl_submitted check"
    except Exception as e:
        log(f"Failed to start cl_submitted check for {changespec.name}: {e}", "red")
        return None


def start_reviewer_comments_check(
    changespec: ChangeSpec,
    workspace_dir: str,
    log: LogCallback,
) -> str | None:
    """Start reviewer comments check as a background process.

    Uses workspace provider plugins to determine whether reviewer comments
    are supported and to generate the check script.

    Args:
        changespec: The ChangeSpec to check.
        workspace_dir: The workspace directory to run the command in.
        log: Logging callback.

    Returns:
        Update message if check was started, None if failed or skipped.
    """
    from sase.workspace_provider import (
        generate_reviewer_comments_script,
        supports_reviewer_comments,
    )

    # When a CL URL is present, ask plugins whether reviewer comments are
    # supported.  Skip if the plugin explicitly returns False.
    if changespec.cl is not None:
        supported = supports_reviewer_comments(changespec.cl)
        if supported is False:
            return None

    script_body = generate_reviewer_comments_script(changespec.name)
    if script_body is None:
        return None

    timestamp = generate_timestamp()
    output_path = _get_check_output_path(
        changespec.name, CHECK_TYPE_REVIEWER_COMMENTS, timestamp
    )

    try:
        _start_background_check(script_body, output_path, workspace_dir)
        return "Started reviewer_comments check"
    except Exception as e:
        log(
            f"Failed to start reviewer_comments check for {changespec.name}: {e}",
            "red",
        )
        return None


def _get_pending_checks(changespec: ChangeSpec) -> list[_PendingCheck]:
    """Get all pending background checks for a ChangeSpec.

    Scans ~/.sase/checks/ for files matching this changespec's name.

    Args:
        changespec: The ChangeSpec to find checks for.

    Returns:
        List of _PendingCheck objects.
    """
    checks_dir = _get_checks_directory()
    if not os.path.exists(checks_dir):
        return []

    # Create safe name pattern
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", changespec.name)
    pending: list[_PendingCheck] = []

    for filename in os.listdir(checks_dir):
        # Parse filename: <safe_name>-<check_type>-<timestamp>.txt
        if not filename.endswith(".txt"):
            continue

        # Match pattern: <safe_name>-<check_type>-<timestamp>.txt
        pattern = rf"^{re.escape(safe_name)}-(\w+)-(\d{{6}}_\d{{6}})\.txt$"
        match = re.match(pattern, filename)
        if match:
            check_type_str = match.group(1)
            timestamp = match.group(2)

            # Validate check type
            if check_type_str in (
                CHECK_TYPE_CL_SUBMITTED,
                CHECK_TYPE_REVIEWER_COMMENTS,
            ):
                pending.append(
                    _PendingCheck(
                        changespec_name=changespec.name,
                        check_type=check_type_str,  # type: ignore[arg-type]
                        timestamp=timestamp,
                        output_path=os.path.join(checks_dir, filename),
                    )
                )

    return pending


def _parse_check_completion(output_path: str) -> tuple[bool, int, str]:
    """Parse a check output file for completion status.

    Args:
        output_path: Path to the output file.

    Returns:
        Tuple of (is_complete, exit_code, content_before_marker).
    """
    if not os.path.exists(output_path):
        return False, -1, ""

    try:
        with open(output_path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False, -1, ""

    # Look for completion marker
    marker_pos = content.rfind(CHECK_COMPLETE_MARKER)
    if marker_pos == -1:
        return False, -1, ""

    # Parse exit code
    try:
        after_marker = content[marker_pos + len(CHECK_COMPLETE_MARKER) :].strip()
        # Format: "EXIT_CODE: <code>"
        if after_marker.startswith("EXIT_CODE:"):
            exit_code = int(after_marker.split(":")[1].strip().split()[0])
        else:
            exit_code = 1
    except (ValueError, IndexError):
        exit_code = 1

    # Get content before marker (the actual command output)
    content_before = content[:marker_pos].strip()

    return True, exit_code, content_before


def _handle_cl_submitted_completion(
    changespec: ChangeSpec,
    exit_code: int,
    log: LogCallback,
) -> str | None:
    """Handle completed is_cl_submitted check.

    Args:
        changespec: The ChangeSpec to update.
        exit_code: The exit code from the check (0 = submitted).
        log: Logging callback.

    Returns:
        Update message if status changed, None otherwise.
    """
    # Update the last_checked timestamp
    update_last_checked(changespec.name)

    # Exit code 0 means submitted, but skip if already Submitted
    if (
        exit_code == 0
        and is_parent_submitted(changespec)
        and changespec.status != "Submitted"
    ):
        from ..sync_cache import clear_cache_entry

        success, old_status, _, _ = transition_changespec_status(
            changespec.file_path,
            changespec.name,
            "Submitted",
            validate=False,
        )

        if success:
            clear_cache_entry(changespec.name)
            return f"Status changed {old_status} -> Submitted"

    return None


def _handle_reviewer_comments_completion(
    changespec: ChangeSpec,
    exit_code: int,
    content: str,
    log: LogCallback,
) -> list[str]:
    """Handle completed critique_comments check for reviewer comments.

    Args:
        changespec: The ChangeSpec to update.
        exit_code: The exit code from the check.
        content: The command output (comment content).
        log: Logging callback.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    # Check if command failed
    if exit_code != 0:
        meaning = _CRITIQUE_COMMENTS_EXIT_CODES.get(exit_code, "unknown error")
        log(
            f"critique_comments failed for {changespec.name}: {meaning} "
            f"(exit code {exit_code})",
            "red",
        )
        return updates

    has_comments = bool(content)

    # Find existing [reviewer] entry
    existing_reviewer_entry: CommentEntry | None = None
    if changespec.comments:
        for entry in changespec.comments:
            if entry.reviewer == "critique":
                existing_reviewer_entry = entry
                break

    if has_comments:
        # If no existing entry, create a new one with the comments file
        if existing_reviewer_entry is None:
            timestamp = generate_timestamp()
            file_path = get_comments_file_path(changespec.name, "critique", timestamp)

            # Save output to file
            with open(file_path, "w") as f:
                f.write(content)

            # Add the new entry (shorten path with ~ for home directory)
            display_path = file_path.replace(str(Path.home()), "~")
            new_entry = CommentEntry(
                reviewer="critique",
                file_path=display_path,
                suffix=None,
            )
            new_comments = list(changespec.comments) if changespec.comments else []
            new_comments.append(new_entry)
            update_changespec_comments_field(
                changespec.file_path,
                changespec.name,
                new_comments,
            )
            updates.append("Added [reviewer] comment entry")
    else:
        # No comments - clear the [reviewer] entry if it exists and:
        # - has no suffix, OR
        # - has a plain suffix (commit reference like "7d")
        if existing_reviewer_entry is not None and (
            existing_reviewer_entry.suffix is None
            or is_plain_suffix(existing_reviewer_entry.suffix)
        ):
            remove_comment_entry(
                changespec.file_path,
                changespec.name,
                "critique",
                changespec.comments,
            )
            updates.append("Removed [critique] comment entry (no comments)")

    return updates


def _cleanup_check_file(output_path: str) -> None:
    """Remove completed check output file."""
    try:
        os.remove(output_path)
    except OSError:
        pass


def check_pending_checks(
    changespec: ChangeSpec,
    log: LogCallback,
) -> list[str]:
    """Poll for completion of pending background checks.

    Scans for pending checks, processes any that have completed,
    and returns update messages.

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.

    Returns:
        List of update messages.
    """
    updates: list[str] = []
    pending = _get_pending_checks(changespec)

    for check in pending:
        is_complete, exit_code, content = _parse_check_completion(check.output_path)

        if not is_complete:
            continue

        # Handle completion based on check type
        if check.check_type == CHECK_TYPE_CL_SUBMITTED:
            update = _handle_cl_submitted_completion(changespec, exit_code, log)
            if update:
                updates.append(update)
        elif check.check_type == CHECK_TYPE_REVIEWER_COMMENTS:
            check_updates = _handle_reviewer_comments_completion(
                changespec, exit_code, content, log
            )
            updates.extend(check_updates)
        # Cleanup the output file
        _cleanup_check_file(check.output_path)

    return updates


def has_pending_check(changespec: ChangeSpec, check_type: CheckType) -> bool:
    """Check if a specific check type is already pending for a ChangeSpec.

    Args:
        changespec: The ChangeSpec to check.
        check_type: The type of check to look for.

    Returns:
        True if a check of this type is pending, False otherwise.
    """
    pending = _get_pending_checks(changespec)
    return any(check.check_type == check_type for check in pending)
