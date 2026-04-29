"""Searchable text extraction for ChangeSpec query matching."""

from ..changespec import ChangeSpec

# Pattern that indicates a running agent in searchable text
# Matches "- (@)" (no message) or "- (@: msg)" (with message)
RUNNING_AGENT_MARKER = "- (@"

# Pattern that indicates a running process in searchable text
# Matches "- ($: PID)" (hook subprocess with PID)
RUNNING_PROCESS_MARKER = "- ($: "


def get_searchable_text(changespec: ChangeSpec) -> str:
    """Extract all searchable text from a ChangeSpec.

    Searches against:
    - name
    - description
    - status (base status without suffixes)
    - project basename (from file_path)
    - parent (if present)
    - cl (if present)
    - kickstart (if present)
    - history notes (if present)
    - hook commands (if present)

    Args:
        changespec: The ChangeSpec to extract text from.

    Returns:
        Combined text for searching (newline-separated).
    """
    parts: list[str] = [
        changespec.name,
        changespec.description,
        changespec.status,
    ]

    # Add project basename (e.g., "myproject" from "~/.sase/projects/myproject/myproject.gp")
    parts.append(changespec.project_name)

    if changespec.parent:
        parts.append(changespec.parent)
    if changespec.cl:
        parts.append(changespec.cl)
    if changespec.kickstart:
        parts.append(changespec.kickstart)

    # Add history notes and suffixes
    if changespec.commits:
        for entry in changespec.commits:
            parts.append(entry.note)
            # Include suffix with prefix for searching (e.g., "(!: NEW PROPOSAL)")
            if entry.suffix:
                if entry.suffix_type == "error":
                    parts.append(f"(!: {entry.suffix})")
                else:
                    parts.append(f"({entry.suffix})")

    # Add hook commands and status line suffixes
    if changespec.hooks:
        for hook in changespec.hooks:
            parts.append(hook.display_command)
            # Include status line suffixes for searching
            if hook.status_lines:
                for sl in hook.status_lines:
                    # Handle running_agent suffix (including empty suffix for RUNNING status)
                    if sl.suffix_type == "running_agent":
                        if sl.suffix:
                            parts.append(f"- (@: {sl.suffix})")
                        else:
                            parts.append("- (@)")
                    # Handle running_process suffix (PID for RUNNING hooks)
                    elif sl.suffix_type == "running_process":
                        parts.append(f"- ($: {sl.suffix})")
                    # Handle killed_process suffix (PID for killed hooks)
                    elif sl.suffix_type == "killed_process":
                        parts.append(f"- (~$: {sl.suffix})")
                    elif sl.suffix:
                        if sl.suffix_type == "error":
                            parts.append(f"(!: {sl.suffix})")
                        else:
                            parts.append(f"({sl.suffix})")

    # Add comment entries and suffixes
    if changespec.comments:
        for comment in changespec.comments:
            parts.append(comment.reviewer)
            parts.append(comment.file_path)
            # Handle running_agent suffix (CRS running)
            if comment.suffix_type == "running_agent":
                if comment.suffix:
                    parts.append(f"- (@: {comment.suffix})")
                else:
                    parts.append("- (@)")
            # Handle running_process suffix (for consistency)
            elif comment.suffix_type == "running_process":
                parts.append(f"- ($: {comment.suffix})")
            # Handle killed_process suffix (for consistency)
            elif comment.suffix_type == "killed_process":
                parts.append(f"- (~$: {comment.suffix})")
            elif comment.suffix:
                if comment.suffix_type == "error":
                    parts.append(f"(!: {comment.suffix})")
                else:
                    parts.append(f"({comment.suffix})")

    # Add mentor status line suffixes
    if changespec.mentors:
        for mentor in changespec.mentors:
            if mentor.status_lines:
                for msl in mentor.status_lines:
                    if msl.suffix_type == "running_agent":
                        if msl.suffix:
                            parts.append(f"- (@: {msl.suffix})")
                        else:
                            parts.append("- (@)")
                    elif msl.suffix:
                        if msl.suffix_type == "error":
                            parts.append(f"(!: {msl.suffix})")
                        else:
                            parts.append(f"({msl.suffix})")

    return "\n".join(parts)
