"""Handler for the 'sase search' command."""

import argparse
import sys
from collections import Counter
from pathlib import Path

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
        _display_markdown(matching, args.query)
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


def _display_markdown(matching: list, query: str) -> None:  # type: ignore[type-arg]
    """Display search results in markdown format."""
    from sase.ace.display_helpers import format_running_claims_aligned
    from sase.ace.hooks import format_timestamp_display
    from sase.running_field import get_claimed_workspaces

    lines: list[str] = []
    status_counts = Counter(cs.status for cs in matching)
    status_breakdown = ", ".join(
        f"{status}: {count}" for status, count in sorted(status_counts.items())
    )

    lines.append("# Search Results")
    lines.append("")
    lines.append(f"- Query: `{_md_escape_inline(query)}`")
    lines.append(f"- Total matches: `{len(matching)}`")
    lines.append(f"- Status breakdown: `{_md_escape_inline(status_breakdown)}`")
    lines.append("")
    lines.append(
        "_Glossary: `PARENT` links to dependency ancestry, `CL/PR` is a review URL,"
        " and status/entry suffixes are preserved verbatim with a type label when present._"
    )

    for index, cs in enumerate(matching, start=1):
        lines.extend(("", f"## {index}. {_md_escape_inline(cs.name)}", ""))
        lines.append("| Field | Value |")
        lines.append("| --- | --- |")
        lines.append(f"| Status (`STATUS`) | `{_md_escape_inline(cs.status)}` |")
        lines.append(
            "| Project File (`file:line`) | "
            f"`{_md_escape_inline(_normalize_home_path(cs.file_path))}:{cs.line_number}` |"
        )
        if cs.parent:
            lines.append(f"| Parent (`PARENT`) | `{_md_escape_inline(cs.parent)}` |")
        if cs.cl:
            lines.append(f"| CL/PR (`CL`) | `{_md_escape_inline(cs.cl)}` |")
        if cs.bug:
            lines.append(f"| Bug (`BUG`) | `{_md_escape_inline(cs.bug)}` |")

        lines.extend(("", "### Purpose (`DESCRIPTION`)"))
        _append_markdown_text(lines, cs.description)

        if cs.kickstart:
            lines.extend(("", "### Kickstart (`KICKSTART`)"))
            _append_markdown_text(lines, cs.kickstart)

        targets = [target for target in cs.test_targets or [] if target != "None"]
        if targets:
            lines.extend(("", "### Test Targets (`TEST TARGETS`)"))
            lines.extend(f"- `{_md_escape_inline(target)}`" for target in targets)

        running_claims = get_claimed_workspaces(cs.file_path)
        if running_claims:
            lines.extend(("", "### Running Workspaces (`RUNNING`)"))
            for ws_col, pid_col, wf_col, cl_name in format_running_claims_aligned(
                running_claims
            ):
                row = (
                    f"`{_md_escape_inline(ws_col.strip())}` | `{_md_escape_inline(pid_col.strip())}`"
                    f" | `{_md_escape_inline(wf_col.strip())}`"
                )
                if cl_name:
                    row += f" | `{_md_escape_inline(cl_name)}`"
                lines.append(f"- {row}")

        if cs.commits:
            lines.extend(("", "### Commits (`COMMITS`)"))
            for entry in cs.commits:
                lines.append(
                    f"- `({entry.display_number})` {_md_escape_inline(entry.note)}"
                    f"{_format_suffix_label(entry.suffix, entry.suffix_type)}"
                )
                if entry.chat:
                    lines.append(
                        f"  - `CHAT`: `{_md_escape_inline(_normalize_home_path(entry.chat))}`"
                    )
                if entry.diff:
                    lines.append(
                        f"  - `DIFF`: `{_md_escape_inline(_normalize_home_path(entry.diff))}`"
                    )
                if entry.plan:
                    lines.append(
                        f"  - `PLAN`: `{_md_escape_inline(_normalize_home_path(entry.plan))}`"
                    )

        if cs.hooks:
            lines.extend(("", "### Hooks (`HOOKS`)"))
            lines.append("")
            lines.append(
                "| Hook Command | Entry | Timestamp | Status | Duration | Suffix |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for hook in cs.hooks:
                status_lines = hook.status_lines or []
                if not status_lines:
                    lines.append(
                        f"| `{_md_escape_inline(hook.display_command)}` | - | - | - | - | - |"
                    )
                    continue
                for status_line in status_lines:
                    ts = format_timestamp_display(status_line.timestamp)
                    duration = (
                        f"`{_md_escape_inline(status_line.duration)}`"
                        if status_line.duration
                        else "-"
                    )
                    suffix = (
                        _format_suffix_table_cell(
                            status_line.suffix, status_line.suffix_type
                        )
                        if status_line.suffix
                        else "-"
                    )
                    lines.append(
                        "| "
                        f"`{_md_escape_inline(hook.display_command)}`"
                        f" | `{_md_escape_inline(status_line.commit_entry_num)}`"
                        f" | `{_md_escape_inline(ts)}`"
                        f" | `{_md_escape_inline(status_line.status)}`"
                        f" | {duration}"
                        f" | {suffix} |"
                    )

        if cs.comments:
            lines.extend(("", "### Comments (`COMMENTS`)"))
            for comment in cs.comments:
                lines.append(
                    f"- `[{_md_escape_inline(comment.reviewer)}]` "
                    f"`{_md_escape_inline(_normalize_home_path(comment.file_path))}`"
                    f"{_format_suffix_label(comment.suffix, comment.suffix_type)}"
                )

        if cs.mentors:
            lines.extend(("", "### Mentors (`MENTORS`)"))
            for mentor in cs.mentors:
                profiles = " ".join(
                    _md_escape_inline(profile) for profile in mentor.profiles
                )
                lines.append(
                    f"- Entry `({_md_escape_inline(mentor.entry_id)})` profiles: {profiles}"
                )
                for status_line in mentor.status_lines or []:
                    duration = (
                        f", duration `{_md_escape_inline(status_line.duration)}`"
                        if status_line.duration
                        else ""
                    )
                    lines.append(
                        "  - "
                        f"`{_md_escape_inline(status_line.profile_name)}:"
                        f"{_md_escape_inline(status_line.mentor_name)}`"
                        f" -> `{_md_escape_inline(status_line.status)}`"
                        f", timestamp `{_md_escape_inline(format_timestamp_display(status_line.timestamp))}`"
                        f"{duration}"
                        f"{_format_suffix_label(status_line.suffix, status_line.suffix_type)}"
                    )

        if cs.timestamps:
            lines.extend(("", "### Timeline (`TIMESTAMPS`)"))
            lines.append("")
            lines.append("| Timestamp | Event | Detail |")
            lines.append("| --- | --- | --- |")
            for entry in cs.timestamps:
                lines.append(
                    f"| `{_md_escape_inline(entry.timestamp)}`"
                    f" | `{_md_escape_inline(entry.event_type)}`"
                    f" | `{_md_escape_inline(entry.detail)}` |"
                )

    print("\n".join(lines))


def _append_markdown_text(lines: list[str], text: str) -> None:
    """Append text as markdown-safe paragraph or fenced block."""
    if "\n" in text:
        lines.append("```text")
        lines.extend(text.splitlines())
        lines.append("```")
    else:
        lines.append(_md_escape_inline(text))


def _format_suffix_label(suffix: str | None, suffix_type: str | None) -> str:
    """Format suffix metadata for bullet list lines."""
    if not suffix:
        return ""
    if suffix_type:
        return (
            f" (status suffix: `{_md_escape_inline(suffix)}`, "
            f"type: `{_md_escape_inline(suffix_type)}`)"
        )
    return f" (status suffix: `{_md_escape_inline(suffix)}`)"


def _format_suffix_table_cell(suffix: str | None, suffix_type: str | None) -> str:
    """Format suffix metadata for table cells."""
    if not suffix:
        return "-"
    if suffix_type:
        return (
            f"`{_md_escape_inline(suffix)}` (type: `{_md_escape_inline(suffix_type)}`)"
        )
    return f"`{_md_escape_inline(suffix)}`"


def _normalize_home_path(path: str) -> str:
    """Normalize home directory prefix to ~ for readability."""
    return path.replace(str(Path.home()), "~")


def _md_escape_inline(value: str) -> str:
    """Escape markdown-sensitive characters for inline/table content."""
    escaped = value.replace("\\", "\\\\")
    for char in ("`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "|", "!"):
        escaped = escaped.replace(char, f"\\{char}")
    return escaped
