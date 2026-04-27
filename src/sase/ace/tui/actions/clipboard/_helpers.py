"""Pure helpers used by clipboard copy actions.

Includes tmux pane capture, multi-target formatting, system clipboard write,
and the fallback ChangeSpec text formatter.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from sase.workspace_provider import get_change_label

if TYPE_CHECKING:
    from ....changespec import ChangeSpec


def capture_tmux_pane() -> str | None:
    """Capture the visible contents of the current tmux pane.

    Returns:
        The pane contents as a string, or None if capture failed.
    """
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def format_multi_copy_content(contents: list[tuple[str, str]]) -> str:
    """Format multiple copy targets with headers and code blocks.

    Args:
        contents: List of (target_name, content) tuples.

    Returns:
        Formatted string with each target prefixed by ### header and wrapped in code blocks.
    """
    parts: list[str] = []
    for target_name, content in contents:
        parts.append(f"### {target_name}")
        parts.append("```")
        parts.append(content)
        parts.append("```")
    return "\n".join(parts)


def copy_to_system_clipboard(content: str) -> bool:
    """Copy content to system clipboard.

    Args:
        content: The text content to copy.

    Returns:
        True if successful, False otherwise.
    """
    if sys.platform == "darwin":
        clipboard_cmd = ["pbcopy"]
    elif sys.platform.startswith("linux"):
        clipboard_cmd = ["xclip", "-selection", "clipboard"]
    else:
        return False

    try:
        subprocess.run(clipboard_cmd, input=content, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def format_changespec_for_clipboard(cs: ChangeSpec) -> str:
    """Format a ChangeSpec as readable text for clipboard.

    Args:
        cs: The ChangeSpec to format.

    Returns:
        Formatted text representation.
    """
    lines: list[str] = []

    # Basic fields
    lines.append(f"NAME: {cs.name}")
    lines.append(f"DESCRIPTION: {cs.description}")
    if cs.parent:
        lines.append(f"PARENT: {cs.parent}")
    if cs.cl:
        label = get_change_label(cs.file_path)
        lines.append(f"{label}: {cs.cl}")
    lines.append(f"STATUS: {cs.status}")
    if cs.bug:
        lines.append(f"BUG: {cs.bug}")
    if cs.test_targets:
        lines.append(f"TEST_TARGETS: {', '.join(cs.test_targets)}")
    if cs.kickstart:
        lines.append(f"KICKSTART: {cs.kickstart}")

    # COMMITS section
    if cs.commits:
        lines.append("")
        lines.append("COMMITS:")
        for entry in cs.commits:
            suffix_part = ""
            if entry.suffix:
                prefix = "!: " if entry.suffix_type == "error" else ""
                suffix_part = f" - ({prefix}{entry.suffix})"

            chat_part = f" [chat: {entry.chat}]" if entry.chat else ""
            diff_part = f" [diff: {entry.diff}]" if entry.diff else ""

            lines.append(
                f"  ({entry.display_number}) {entry.note}{suffix_part}{chat_part}{diff_part}"
            )

    # HOOKS section
    if cs.hooks:
        lines.append("")
        lines.append("HOOKS:")
        for hook in cs.hooks:
            lines.append(f"  {hook.command}")
            if hook.status_lines:
                for sl in hook.status_lines:
                    suffix_part = ""
                    if sl.suffix:
                        prefix_map = {
                            "error": "!: ",
                            "running_agent": "@: ",
                            "killed_agent": "~@: ",
                            "running_process": "$: ",
                            "pending_dead_process": "?$: ",
                            "killed_process": "~$: ",
                            "summarize_complete": "%: ",
                        }
                        prefix = prefix_map.get(sl.suffix_type or "", "")
                        suffix_part = f" - ({prefix}{sl.suffix})"
                        if sl.summary:
                            suffix_part = f" - ({prefix}{sl.suffix} | {sl.summary})"

                    duration_part = f" ({sl.duration})" if sl.duration else ""
                    lines.append(
                        f"    ({sl.commit_entry_num}) [{sl.timestamp}] {sl.status}{duration_part}{suffix_part}"
                    )

    # COMMENTS section
    if cs.comments:
        lines.append("")
        lines.append("COMMENTS:")
        for comment in cs.comments:
            suffix_part = ""
            if comment.suffix:
                prefix = "!: " if comment.suffix_type == "error" else ""
                if comment.suffix_type == "running_agent":
                    prefix = "@: "
                suffix_part = f" - ({prefix}{comment.suffix})"
            lines.append(f"  [{comment.reviewer}] {comment.file_path}{suffix_part}")

    # MENTORS section
    if cs.mentors:
        lines.append("")
        lines.append("MENTORS:")
        for mentor_entry in cs.mentors:
            draft_marker = " (Draft)" if mentor_entry.is_draft else ""
            lines.append(
                f"  ({mentor_entry.entry_id}) {' '.join(mentor_entry.profiles)}{draft_marker}"
            )
            if mentor_entry.status_lines:
                for msl in mentor_entry.status_lines:
                    suffix_part = ""
                    if msl.suffix:
                        prefix_map = {
                            "running_agent": "@: ",
                            "error": "!: ",
                        }
                        prefix = prefix_map.get(msl.suffix_type or "", "")
                        suffix_part = f" - ({prefix}{msl.suffix})"
                    elif msl.duration:
                        suffix_part = f" - ({msl.duration})"

                    ts_part = f"[{msl.timestamp}] " if msl.timestamp else ""
                    lines.append(
                        f"    | {ts_part}{msl.profile_name}:{msl.mentor_name} - {msl.status}{suffix_part}"
                    )

    return "\n".join(lines)
