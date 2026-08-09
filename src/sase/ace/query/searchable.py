"""Searchable text extraction for Patch query matching."""

from ..patch import Patch

# Pattern that indicates a running agent in searchable text
# Matches "- (@)" (no message) or "- (@: msg)" (with message)
RUNNING_AGENT_MARKER = "- (@"

# Pattern that indicates a running process in searchable text
# Matches "- ($: PID)" (hook subprocess with PID)
RUNNING_PROCESS_MARKER = "- ($: "


def get_searchable_text(patch: Patch) -> str:
    """Extract all searchable text from a Patch.

    Searches against:
    - name
    - description
    - status (base status without suffixes)
    - project basename (from file_path)
    - parent (if present)
    - cl (if present)
    - history notes (if present)
    - hook commands (if present)

    Args:
        patch: The Patch to extract text from.

    Returns:
        Combined text for searching (newline-separated).
    """
    parts: list[str] = [
        patch.name,
        patch.description,
        patch.status,
    ]

    # Add project basename (e.g., "myproject" from "~/.sase/projects/myproject/myproject.sase")
    parts.append(patch.project_name)
    parts.extend(getattr(patch, "refs", ()) or ())

    if patch.parent:
        parts.append(patch.parent)
    if patch.pr_url:
        parts.append(patch.pr_url)

    # Add history notes and suffixes
    if patch.commits:
        for entry in patch.commits:
            parts.append(entry.note)
            # Include suffix with prefix for searching (e.g., "(!: NEW PROPOSAL)")
            if entry.suffix:
                if entry.suffix_type == "error":
                    parts.append(f"(!: {entry.suffix})")
                else:
                    parts.append(f"({entry.suffix})")

    # Add hook commands and status line suffixes
    if patch.hooks:
        for hook in patch.hooks:
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
    if patch.comments:
        for comment in patch.comments:
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
    if patch.mentors:
        for mentor in patch.mentors:
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
