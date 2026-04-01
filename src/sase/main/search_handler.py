"""Handler for the 'sase search' command."""

import argparse
import sys
from pathlib import Path
from typing import Any

from sase.ace.query import QueryParseError


def handle_search_command(args: argparse.Namespace) -> None:
    """Handle the 'sase search' command."""
    from sase.ace.changespec import find_all_changespecs
    from sase.ace.query import evaluate_query, parse_query

    try:
        parsed_query = parse_query(args.query)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    all_changespecs = find_all_changespecs()
    matching = [
        cs
        for cs in all_changespecs
        if evaluate_query(parsed_query, cs, all_changespecs)
    ]

    if not matching:
        print("No ChangeSpecs match the query.")
        sys.exit(0)

    if args.format == "rich":
        _display_rich(matching)
    elif args.format == "markdown":
        _display_markdown(matching)
    else:
        _display_plain(matching)

    sys.exit(0)


def _display_rich(matching: list) -> None:  # type: ignore[type-arg]
    """Display search results with rich formatting."""
    from collections import Counter

    from sase.ace.display import display_changespec
    from sase.ace.display_helpers import get_status_color
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    for cs in matching:
        display_changespec(cs, console)

    # Print summary panel
    summary = Text()

    # Count and status breakdown
    status_counts = Counter(cs.status for cs in matching)
    breakdown = ", ".join(
        f"{count} {status}" for status, count in sorted(status_counts.items())
    )
    summary.append(
        f"Found {len(matching)} ChangeSpec(s): {breakdown}\n\n", style="bold"
    )

    # One-line per ChangeSpec
    for cs in matching:
        status_color = get_status_color(cs.status)
        summary.append(f"  {cs.name}", style="bold #00D7AF")
        summary.append(f" [{cs.status}]\n", style=f"bold {status_color}")

    summary.rstrip()
    console.print(Panel(summary, title="Summary", border_style="green"))


def _display_plain(matching: list) -> None:  # type: ignore[type-arg]
    """Display search results in plain text format."""
    from sase.ace.display_helpers import format_running_claims_aligned
    from sase.ace.hooks import format_timestamp_display
    from sase.running_field import get_claimed_workspaces

    for cs in matching:
        file_path = cs.file_path.replace(str(Path.home()), "~")
        print(f"--- {file_path}:{cs.line_number} ---")

        # BUG field (from ChangeSpec)
        if cs.bug:
            print(f"BUG: {cs.bug}")

        # RUNNING field (from ProjectSpec)
        running_claims = get_claimed_workspaces(cs.file_path)
        if running_claims:
            print("RUNNING:")
            formatted_claims = format_running_claims_aligned(running_claims)
            for ws_col, pid_col, wf_col, cl_name in formatted_claims:
                if cl_name:
                    print(f"  {ws_col} | {pid_col} | {wf_col} | {cl_name}")
                else:
                    print(f"  {ws_col} | {pid_col} | {wf_col}")

        print(f"NAME: {cs.name}")
        print("DESCRIPTION:")
        for line in cs.description.split("\n"):
            print(f"  {line}")
        if cs.kickstart:
            print("KICKSTART:")
            for line in cs.kickstart.split("\n"):
                print(f"  {line}")
        if cs.parent:
            print(f"PARENT: {cs.parent}")
        if cs.cl:
            print(f"CL: {cs.cl}")
        print(f"STATUS: {cs.status}")
        if cs.test_targets:
            targets = [t for t in cs.test_targets if t != "None"]
            if targets:
                print(f"TEST TARGETS: {', '.join(targets)}")
        if cs.commits:
            print("COMMITS:")
            for entry in cs.commits:
                suffix_str = f" - ({entry.suffix})" if entry.suffix else ""
                print(f"  ({entry.display_number}) {entry.note}{suffix_str}")
                if entry.chat:
                    chat_path = entry.chat.replace(str(Path.home()), "~")
                    print(f"      | CHAT: {chat_path}")
                if entry.diff:
                    diff_path = entry.diff.replace(str(Path.home()), "~")
                    print(f"      | DIFF: {diff_path}")
        if cs.hooks:
            print("HOOKS:")
            for hook in cs.hooks:
                print(f"  {hook.command}")
                for sl in hook.status_lines or []:
                    suffix_str = f" - ({sl.suffix})" if sl.suffix else ""
                    duration_str = f" ({sl.duration})" if sl.duration else ""
                    ts_str = format_timestamp_display(sl.timestamp)
                    print(
                        f"      | ({sl.commit_entry_num}) [{ts_str}] {sl.status}"
                        f"{duration_str}{suffix_str}"
                    )
        if cs.comments:
            print("COMMENTS:")
            for comment in cs.comments:
                suffix_str = f" - ({comment.suffix})" if comment.suffix else ""
                comment_path = comment.file_path.replace(str(Path.home()), "~")
                print(f"  [{comment.reviewer}] {comment_path}{suffix_str}")
        if cs.mentors:
            print("MENTORS:")
            for mentor in cs.mentors:
                profiles_str = " ".join(mentor.profiles)
                print(f"  ({mentor.entry_id}) {profiles_str}")
                # Print status lines for each mentor entry
                if mentor.status_lines:
                    for msl in mentor.status_lines:
                        ts_str = (
                            f"[{format_timestamp_display(msl.timestamp)}] "
                            if msl.timestamp
                            else ""
                        )
                        duration_str = f" - ({msl.duration})" if msl.duration else ""
                        suffix_str = f" - ({msl.suffix})" if msl.suffix else ""
                        print(
                            f"      | {ts_str}{msl.profile_name}:{msl.mentor_name}"
                            f" - {msl.status}{duration_str}{suffix_str}"
                        )
        print()  # Blank line between ChangeSpecs


def _md_status_emoji(status: str) -> str:
    """Map hook/mentor status to emoji."""
    return {
        "PASSED": "✅",
        "FAILED": "❌",
        "RUNNING": "🔄",
        "STARTING": "🔄",
        "KILLED": "💀",
        "DEAD": "💀",
        "COMMENTED": "💬",
    }.get(status, "")


def _md_suffix(suffix: str | None, suffix_type: str | None) -> str:
    """Render a suffix with appropriate emoji prefix based on suffix_type."""
    if not suffix:
        return ""
    emoji = {
        "error": "⚠️",
        "running_agent": "🤖",
        "killed_agent": "💀",
        "running_process": "⚙️",
        "killed_process": "🛑",
        "pending_dead_process": "🛑",
        "summarize_complete": "📋",
        "metahook_complete": "📋",
        "rejected_proposal": "🚫",
    }.get(suffix_type or "", "")
    return f"{emoji} {suffix}" if emoji else suffix


def _md_path(path: str) -> str:
    """Convert path to tilde-relative backtick-wrapped form."""
    return f"`{path.replace(str(Path.home()), '~')}`"


def _md_changespec(cs: Any) -> str:
    """Render a single ChangeSpec to markdown string."""
    lines: list[str] = []

    # Header
    lines.append(f"## {cs.name}")
    lines.append("")

    # Status · Project line
    lines.append(f"**Status:** {cs.status} · **Project:** {cs.project_basename}")
    lines.append("")

    # Description as blockquote
    for desc_line in cs.description.split("\n"):
        lines.append(f"> {desc_line}" if desc_line else ">")
    lines.append("")

    # Metadata table (only when at least one optional field present)
    kickstart_multiline = cs.kickstart and "\n" in cs.kickstart
    kickstart_in_table = cs.kickstart and not kickstart_multiline
    if cs.parent or cs.cl or cs.bug or kickstart_in_table:
        lines.append("| Field | Value |")
        lines.append("| ----- | ----- |")
        if cs.parent:
            lines.append(f"| Parent | `{cs.parent}` |")
        if cs.cl:
            lines.append(f"| CL/PR | {cs.cl} |")
        if cs.bug:
            lines.append(f"| Bug | {cs.bug} |")
        if kickstart_in_table:
            lines.append(f"| Kickstart | {cs.kickstart} |")
        lines.append("")

    # Multi-line kickstart as separate blockquote
    if kickstart_multiline:
        lines.append("### Kickstart")
        lines.append("")
        for ks_line in cs.kickstart.split("\n"):
            lines.append(f"> {ks_line}" if ks_line else ">")
        lines.append("")

    # Commits
    if cs.commits:
        lines.append("### Commits")
        lines.append("")
        for i, entry in enumerate(cs.commits, 1):
            suffix_str = ""
            if entry.suffix:
                suffix_str = f" — {_md_suffix(entry.suffix, entry.suffix_type)}"
            lines.append(f"{i}. **({entry.display_number})** {entry.note}{suffix_str}")
            if entry.chat:
                lines.append(f"   - Chat: {_md_path(entry.chat)}")
            if entry.diff:
                lines.append(f"   - Diff: {_md_path(entry.diff)}")
            if entry.plan:
                lines.append(f"   - Plan: {_md_path(entry.plan)}")
        lines.append("")

    # Hooks (flat table with all status lines)
    if cs.hooks:
        all_status_lines = [
            (hook, sl) for hook in cs.hooks for sl in (hook.status_lines or [])
        ]
        if all_status_lines:
            lines.append("### Hooks")
            lines.append("")
            lines.append("| Hook | Entry | Timestamp | Status | Duration | Note |")
            lines.append("| ---- | ----- | --------- | ------ | -------- | ---- |")
            for hook, sl in all_status_lines:
                emoji = _md_status_emoji(sl.status)
                status_str = f"{emoji} {sl.status}" if emoji else sl.status
                duration = sl.duration or ""
                note = _md_suffix(sl.suffix, sl.suffix_type) if sl.suffix else ""
                lines.append(
                    f"| `{hook.display_command}` | ({sl.commit_entry_num}) "
                    f"| `{sl.timestamp}` | {status_str} | {duration} | {note} |"
                )
            lines.append("")

    # Comments
    if cs.comments:
        lines.append("### Comments")
        lines.append("")
        for comment in cs.comments:
            suffix_str = ""
            if comment.suffix:
                suffix_str = f" — {_md_suffix(comment.suffix, comment.suffix_type)}"
            lines.append(
                f"- **[{comment.reviewer}]** {_md_path(comment.file_path)}{suffix_str}"
            )
        lines.append("")

    # Mentors
    if cs.mentors:
        lines.append("### Mentors")
        lines.append("")
        for mentor in cs.mentors:
            profiles_str = " ".join(mentor.profiles)
            lines.append(f"- **({mentor.entry_id})** {profiles_str}")
            for msl in mentor.status_lines or []:
                emoji = _md_status_emoji(msl.status)
                status_str = f"{emoji} {msl.status}" if emoji else msl.status
                duration_str = f" ({msl.duration})" if msl.duration else ""
                suffix_str = ""
                if msl.suffix:
                    suffix_str = f" — {_md_suffix(msl.suffix, msl.suffix_type)}"
                lines.append(
                    f"  - `{msl.profile_name}:{msl.mentor_name}` — "
                    f"{status_str}{duration_str}{suffix_str}"
                )
        lines.append("")

    return "\n".join(lines).rstrip()


def _md_summary(matching: list[Any]) -> str:
    """Render the summary section."""
    from collections import Counter

    lines: list[str] = []
    lines.append("## Summary")
    lines.append("")

    status_counts = Counter(cs.status for cs in matching)
    breakdown = ", ".join(
        f"{count} {status}" for status, count in sorted(status_counts.items())
    )
    lines.append(f"**Found {len(matching)} ChangeSpec(s):** {breakdown}")
    lines.append("")

    lines.append("| Name | Status | Project |")
    lines.append("| ---- | ------ | ------- |")
    for cs in matching:
        lines.append(f"| `{cs.name}` | {cs.status} | {cs.project_basename} |")

    return "\n".join(lines)


def _display_markdown(matching: list) -> None:  # type: ignore[type-arg]
    """Display search results in markdown format."""
    parts = [_md_changespec(cs) for cs in matching]
    output = "\n\n---\n\n".join(parts)
    output += "\n\n---\n\n" + _md_summary(matching)
    print(output)
