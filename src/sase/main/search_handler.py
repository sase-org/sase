"""Handler for the 'sase search' command."""

import argparse
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
import re

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
    """Display search results as markdown."""
    from sase.ace.display_helpers import format_running_claims_aligned
    from sase.ace.hooks import format_timestamp_display
    from sase.running_field import get_claimed_workspaces
    from sase.workspace_provider import get_change_label

    anchors = _build_anchors(cs.name for cs in matching)
    print("# ChangeSpec Search Results")
    print()
    print(f"**Query:** `{query}`")
    print(f"**Matches:** {len(matching)}")
    print()

    for cs, anchor in zip(matching, anchors, strict=False):
        file_path = _normalize_home_path(cs.file_path)
        print(f'<a id="{anchor}"></a>')
        print(f"## {_escape_markdown_inline(cs.name)}")
        print()
        print(f"- **Status:** {_escape_markdown_inline(cs.status)}")
        print(f"- **Path:** `{file_path}:{cs.line_number}`")
        if cs.parent:
            print(f"- **Parent:** {_escape_markdown_inline(cs.parent)}")
        if cs.cl:
            change_label = get_change_label(cs.file_path)
            print(f"- **{change_label}:** {_escape_markdown_inline(cs.cl)}")
        if cs.bug:
            print(f"- **Bug:** {_escape_markdown_inline(cs.bug)}")
        if cs.test_targets:
            test_targets = [t for t in cs.test_targets if t != "None"]
            if test_targets:
                targets_str = ", ".join(
                    _escape_markdown_inline(t) for t in test_targets
                )
                print(f"- **Test Targets:** {targets_str}")
        print()

        if cs.description:
            print("### Description")
            _print_markdown_quote_block(cs.description)
            print()

        if cs.kickstart:
            print("### Kickstart")
            _print_markdown_quote_block(cs.kickstart)
            print()

        running_claims = get_claimed_workspaces(cs.file_path)
        if running_claims:
            print("### Running")
            print("| Workspace | PID | Workflow | ChangeSpec |")
            print("| --- | --- | --- | --- |")
            formatted_claims = format_running_claims_aligned(running_claims)
            for ws_col, pid_col, wf_col, cl_name in formatted_claims:
                ws = _escape_markdown_inline(ws_col.strip())
                pid = _escape_markdown_inline(pid_col.strip())
                workflow = _escape_markdown_inline(wf_col.strip())
                cl_display = _escape_markdown_inline(cl_name) if cl_name else ""
                print(f"| {ws} | {pid} | {workflow} | {cl_display} |")
            print()

        if cs.commits:
            print("### Commits")
            for entry in cs.commits:
                suffix_str = (
                    f" - ({_escape_markdown_inline(entry.suffix)})"
                    if entry.suffix
                    else ""
                )
                print(
                    f"- ({entry.display_number}) "
                    f"{_escape_markdown_inline(entry.note)}{suffix_str}"
                )
                if entry.chat:
                    chat_path = _normalize_home_path(entry.chat)
                    print(f"  - `CHAT:` `{chat_path}`")
                if entry.diff:
                    diff_path = _normalize_home_path(entry.diff)
                    print(f"  - `DIFF:` `{diff_path}`")
            print()

        if cs.hooks:
            print("### Hooks")
            for hook in cs.hooks:
                print(f"- `{hook.command}`")
                for sl in hook.status_lines or []:
                    suffix_str = (
                        f" - ({_escape_markdown_inline(sl.suffix)})"
                        if sl.suffix
                        else ""
                    )
                    duration_str = f" ({sl.duration})" if sl.duration else ""
                    ts_str = format_timestamp_display(sl.timestamp)
                    status = _escape_markdown_inline(sl.status)
                    print(
                        f"  - ({sl.commit_entry_num}) {ts_str} "
                        f"{status}{duration_str}{suffix_str}"
                    )
            print()

        if cs.comments:
            print("### Comments")
            for comment in cs.comments:
                suffix_str = (
                    f" - ({_escape_markdown_inline(comment.suffix)})"
                    if comment.suffix
                    else ""
                )
                reviewer = _escape_markdown_inline(comment.reviewer)
                comment_path = _normalize_home_path(comment.file_path)
                print(f"- [{reviewer}] `{comment_path}`{suffix_str}")
            print()

        if cs.mentors:
            print("### Mentors")
            for mentor in cs.mentors:
                profiles_str = " ".join(
                    _escape_markdown_inline(p) for p in mentor.profiles
                )
                print(f"- ({mentor.entry_id}) {profiles_str}")
                for msl in mentor.status_lines or []:
                    ts_str = (
                        f"{format_timestamp_display(msl.timestamp)} "
                        if msl.timestamp
                        else ""
                    )
                    duration_str = f" - ({msl.duration})" if msl.duration else ""
                    suffix_str = (
                        f" - ({_escape_markdown_inline(msl.suffix)})"
                        if msl.suffix
                        else ""
                    )
                    profile_mentor = (
                        f"{_escape_markdown_inline(msl.profile_name)}:"
                        f"{_escape_markdown_inline(msl.mentor_name)}"
                    )
                    status = _escape_markdown_inline(msl.status)
                    print(
                        f"  - {ts_str}{profile_mentor} - "
                        f"{status}{duration_str}{suffix_str}"
                    )
            print()

    _print_markdown_summary(matching, anchors)


def _normalize_home_path(path: str) -> str:
    """Normalize absolute home directory prefixes to '~'."""
    return path.replace(str(Path.home()), "~")


def _escape_markdown_inline(text: str) -> str:
    """Escape markdown control chars for inline text."""
    escaped = text.replace("\\", "\\\\")
    return re.sub(r"([`*_{}\[\]()+\-!|<>])", r"\\\1", escaped)


def _print_markdown_quote_block(text: str) -> None:
    """Print a multiline markdown blockquote."""
    for line in text.splitlines():
        if line:
            print(f"> {line}")
        else:
            print(">")


def _build_anchors(names: Iterable[str]) -> list[str]:
    """Build stable unique markdown anchors from ChangeSpec names."""
    counters: dict[str, int] = {}
    anchors: list[str] = []
    for name in names:
        base = _slugify(name)
        count = counters.get(base, 0)
        counters[base] = count + 1
        anchor = base if count == 0 else f"{base}-{count + 1}"
        anchors.append(anchor)
    return anchors


def _slugify(text: str) -> str:
    """Generate a markdown-anchor-friendly slug."""
    cleaned = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    compact = re.sub(r"\s+", "-", cleaned).strip("-")
    return compact or "changespec"


def _print_markdown_summary(matching: list, anchors: list[str]) -> None:  # type: ignore[type-arg]
    """Print markdown summary with status breakdown and quick links."""
    status_counts = Counter(cs.status for cs in matching)

    print("## Summary")
    print()
    print("### Status Breakdown")
    for status, count in sorted(status_counts.items()):
        print(f"- {_escape_markdown_inline(status)}: {count}")
    print()
    print("### Quick Links")
    for cs, anchor in zip(matching, anchors, strict=False):
        print(f"- [{_escape_markdown_inline(cs.name)}](#{anchor})")
