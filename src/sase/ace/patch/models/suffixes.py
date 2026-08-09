"""Patch suffix constants and classification helpers."""

# Error suffix messages that require "!: " prefix when formatting/displaying
ERROR_SUFFIX_MESSAGES = frozenset(
    {
        "ZOMBIE",
        "Hook Command Failed",
        "summarize-hook Failed",
        "fix-hook Failed",
        "Unresolved Critique Comments",
    }
)


def is_error_suffix(suffix: str | None) -> bool:
    """Check if a suffix indicates an error condition requiring '!: ' prefix.

    Args:
        suffix: The suffix value (message part only, not including "!: " prefix).

    Returns:
        True if the suffix indicates an error, False otherwise.
    """
    return suffix is not None and suffix in ERROR_SUFFIX_MESSAGES


def is_running_agent_suffix(suffix: str | None) -> bool:
    """Check if a suffix indicates a running agent requiring '@: ' prefix.

    Running agent suffixes contain timestamps (YYmmdd_HHMMSS format) that indicate
    an agent is actively working. Displayed with bold white on orange background.

    Args:
        suffix: The suffix value (message part only, not including "@: " prefix).

    Returns:
        True if the suffix is a running agent format, False otherwise.
    """
    if suffix is None:
        return False
    # Format with PID: <agent>-<PID>-YYmmdd_HHMMSS (e.g., fix_hook-12345-251230_151429)
    # Split by "-" and check for: agent, PID (digits), timestamp (13 chars with "_" at pos 6)
    if "-" in suffix:
        parts = suffix.split("-")
        if len(parts) >= 3:
            ts = parts[-1]
            pid = parts[-2]
            if pid.isdigit() and len(ts) == 13 and ts[6] == "_":
                return True
    return False


def is_running_process_suffix(suffix: str | None) -> bool:
    """Check if a suffix indicates a running hook process requiring '$: ' prefix.

    Running process suffixes are process IDs (PIDs) that indicate a hook
    subprocess is actively running. Displayed with bold black on yellow background.

    Args:
        suffix: The suffix value (message part only, not including "$: " prefix).

    Returns:
        True if the suffix is a PID (all digits), False otherwise.
    """
    if suffix is None:
        return False
    # PID format: all digits, typically 4-6 chars but could be more
    # Use >= 4 to distinguish from commit references (1-3 digits like "3", "12")
    return suffix.isdigit() and len(suffix) >= 4


def is_plain_suffix(suffix: str | None) -> bool:
    """Check if a suffix is a plain suffix (commit reference, not error/running).

    Plain suffixes are commit references like "7d" or "3a" that indicate
    which commit addressed the comments. These are safe to remove when
    the comments have been resolved.

    Args:
        suffix: The suffix value.

    Returns:
        True if the suffix is plain (not error, not running agent/process).
    """
    if suffix is None:
        return False
    return (
        not is_error_suffix(suffix)
        and not is_running_agent_suffix(suffix)
        and not is_running_process_suffix(suffix)
    )


# Valid suffix_type values for HookStatusLine, Stitch, CommentEntry:
# - "error": Displayed with "!: " prefix (red color)
# - "running_agent": Displayed with "@: " prefix (agent is actively working)
# - "killed_agent": Displayed with "~@: " prefix (agent was killed, faded orange)
# - "running_process": Displayed with "$: " prefix (hook subprocess running with PID)
# - "pending_dead_process": Displayed with "?$: " prefix (process dead, waiting for timeout)
# - "killed_process": Displayed with "~$: " prefix (hook process was killed)
# - "plain": Displayed without any prefix (explicitly no prefix, bypasses auto-detect)
# - "summarize_complete": Summary generated, ready for fix-hook (displayed as plain suffix)
# - None: Falls back to message-based auto-detection of type


def extract_pid_from_agent_suffix(suffix: str | None) -> int | None:
    """Extract PID from an agent suffix format: <agent>-<PID>-<timestamp>.

    Args:
        suffix: The suffix value (e.g., "fix_hook-12345-251230_151429").

    Returns:
        The PID as an integer, or None if the suffix doesn't match the expected format.
    """
    if suffix is None:
        return None
    if "-" not in suffix:
        return None
    parts = suffix.split("-")
    if len(parts) < 3:
        return None
    pid_str = parts[-2]
    if not pid_str.isdigit():
        return None
    return int(pid_str)


def get_base_status(status: str) -> str:
    """Get base status without legacy READY TO MAIL suffix.

    Args:
        status: The STATUS value.

    Returns:
        The base status value (e.g., "Ready").
    """
    # Strip legacy READY TO MAIL suffix for backward compatibility
    result = status.replace(" - (!: READY TO MAIL)", "").strip()
    return result if result else status
