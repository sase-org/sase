"""Pure helpers used by clipboard copy actions.

Includes tmux pane capture, multi-target formatting, and the fallback
Patch text formatter.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ....patch import Patch


# Match the established ACE preview-read ceiling. Copy targets may read the
# entire backing artifact, so both individual values and assembled marked sets
# must remain bounded.
MAX_COPY_CONTENT_BYTES = 512_000


@dataclass(frozen=True, slots=True)
class _CappedCopyContent:
    """One bounded copy value and whether any input was truncated."""

    value: str
    truncated: bool


def cap_copy_content(
    content: str,
    *,
    max_bytes: int = MAX_COPY_CONTENT_BYTES,
) -> _CappedCopyContent:
    """Bound UTF-8 content and append an explicit truncation banner."""

    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return _CappedCopyContent(content, False)

    banner = f"\n\n[Truncated at {max_bytes:,} bytes]"
    banner_bytes = banner.encode("utf-8")
    available = max(0, max_bytes - len(banner_bytes))
    clipped = encoded[:available].decode("utf-8", errors="ignore")
    return _CappedCopyContent(f"{clipped}{banner}", True)


def format_multi_copy_content_capped(
    contents: list[tuple[str, str]],
    *,
    max_bytes: int = MAX_COPY_CONTENT_BYTES,
) -> _CappedCopyContent:
    """Format a bounded, fenced multi-item content dump."""

    parts: list[str] = []
    truncated = False
    for target_name, content in contents:
        capped = cap_copy_content(content, max_bytes=max_bytes)
        truncated = truncated or capped.truncated
        parts.append(f"### {target_name}")
        parts.append("```")
        parts.append(capped.value)
        parts.append("```")
    combined = cap_copy_content("\n".join(parts), max_bytes=max_bytes)
    return _CappedCopyContent(combined.value, truncated or combined.truncated)


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


def format_markdown_link(label: str, target: str) -> str:
    """Render a Markdown link while escaping label delimiters."""

    safe_label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}]({target})"


def format_patch_for_clipboard(cs: Patch) -> str:
    """Format a Patch as readable text for clipboard.

    Args:
        cs: The Patch to format.

    Returns:
        Formatted text representation.
    """
    lines: list[str] = []

    # Basic fields
    lines.append(f"NAME: {cs.name}")
    lines.append(f"DESCRIPTION: {cs.description}")
    if cs.parent:
        lines.append(f"PARENT: {cs.parent}")
    if cs.pr_url:
        lines.append(f"PR: {cs.pr_url}")
    lines.append(f"STATUS: {cs.status}")
    if cs.bug:
        lines.append(f"BUG: {cs.bug}")
    if cs.refs:
        lines.append("REFS:")
        lines.extend(f"  {reference}" for reference in cs.refs)
    # STITCHES section
    if cs.stitches:
        lines.append("")
        lines.append("STITCHES:")
        for entry in cs.stitches:
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
                        f"    ({sl.stitch_num}) [{sl.timestamp}] {sl.status}{duration_part}{suffix_part}"
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


format_changespec_for_clipboard = (
    format_patch_for_clipboard  # legacy compatibility alias
)
