"""Handler for the 'sase changespec search' command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sase.ace.query import QueryParseError
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    humanize_cl_name,
    load_project_display_snapshot,
)


def handle_search_command(args: argparse.Namespace) -> None:
    """Handle the 'sase changespec search' command."""
    from sase.ace.patch import find_all_patches
    from sase.ace.query import parse_query
    from sase.core.query_facade import evaluate_query_many

    try:
        parse_query(args.query)
    except QueryParseError as e:
        print(f"Error: Invalid query: {e}")
        sys.exit(1)

    all_patches = find_all_patches()
    mask = evaluate_query_many(args.query, all_patches)
    matching = [cs for cs, keep in zip(all_patches, mask, strict=True) if keep]

    if not matching:
        print("No Patches match the query.")
        sys.exit(0)

    project_display_snapshot = load_project_display_snapshot()
    if args.format == "rich":
        _display_rich(
            matching,
            project_display_snapshot=project_display_snapshot,
        )
    elif args.format == "markdown":
        _display_markdown(
            matching,
            query=args.query,
            project_display_snapshot=project_display_snapshot,
        )
    else:
        _display_plain(
            matching,
            project_display_snapshot=project_display_snapshot,
        )

    sys.exit(0)


def _display_rich(
    matching: list,  # type: ignore[type-arg]
    *,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
) -> None:
    """Display search results with rich formatting."""
    from collections import Counter

    from sase.ace.display import display_patch
    from sase.ace.display_helpers import get_status_color
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    console = Console()
    for cs in matching:
        display_patch(
            cs,
            console,
            project_display_snapshot=project_display_snapshot,
        )

    # Print summary panel
    summary = Text()

    # Count and status breakdown
    status_counts = Counter(cs.status for cs in matching)
    breakdown = ", ".join(
        f"{count} {status}" for status, count in sorted(status_counts.items())
    )
    summary.append(f"Found {len(matching)} Patch(s): {breakdown}\n\n", style="bold")

    # One-line per Patch
    for cs in matching:
        status_color = get_status_color(cs.status)
        display_name = humanize_cl_name(
            cs.name,
            snapshot=project_display_snapshot,
        )
        summary.append(f"  {display_name}", style="bold #00D7AF")
        summary.append(f" [{cs.status}]\n", style=f"bold {status_color}")

    summary.rstrip()
    console.print(Panel(summary, title="Summary", border_style="green"))


def _display_plain(
    matching: list,  # type: ignore[type-arg]
    *,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
) -> None:
    """Display search results in plain text format."""
    from sase.ace.display_helpers import format_running_claims_aligned
    from sase.ace.hooks import format_timestamp_display
    from sase.running_field import get_claimed_workspaces

    for cs in matching:
        file_path = cs.file_path.replace(str(Path.home()), "~")
        print(f"--- {file_path}:{cs.line_number} ---")

        # BUG field (from Patch)
        if cs.bug:
            print(f"BUG: {cs.bug}")

        # RUNNING field (from ProjectSpec)
        running_claims = get_claimed_workspaces(cs.file_path)
        if running_claims:
            print("RUNNING:")
            formatted_claims = format_running_claims_aligned(running_claims)
            for ws_col, pid_col, wf_col, cl_name in formatted_claims:
                if cl_name:
                    display_cl_name = humanize_cl_name(
                        cl_name,
                        snapshot=project_display_snapshot,
                    )
                    print(f"  {ws_col} | {pid_col} | {wf_col} | {display_cl_name}")
                else:
                    print(f"  {ws_col} | {pid_col} | {wf_col}")

        print(
            "NAME: "
            + humanize_cl_name(
                cs.name,
                snapshot=project_display_snapshot,
            )
        )
        print("DESCRIPTION:")
        for line in cs.description.split("\n"):
            print(f"  {line}")
        if cs.parent:
            print(
                "PARENT: "
                + humanize_cl_name(
                    cs.parent,
                    snapshot=project_display_snapshot,
                )
            )
        if cs.pr_url:
            print(f"PR: {cs.pr_url}")
        print(f"STATUS: {cs.status}")
        if cs.refs:
            print("REFS:")
            for reference in cs.refs:
                print(f"  {reference}")
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
        print()  # Blank line between Patches


# ---------------------------------------------------------------------------
# Markdown format
# ---------------------------------------------------------------------------

_SUFFIX_EMOJI: dict[str | None, str] = {
    "error": ":x:",
    "running_agent": ":arrows_counterclockwise:",
    "running_process": ":arrows_counterclockwise:",
    "killed_agent": ":skull:",
    "killed_process": ":skull:",
    "pending_dead_process": ":warning:",
    "rejected_proposal": ":warning:",
    "summarize_complete": ":white_check_mark:",
    "metahook_complete": ":white_check_mark:",
}

_STATUS_EMOJI: dict[str, str] = {
    "PASSED": ":white_check_mark: Passed",
    "COMMENTED": ":white_check_mark: Commented",
    "SUBMITTED": ":white_check_mark: Submitted",
    "FAILED": ":x: Failed",
    "DEAD": ":skull: Dead",
    "KILLED": ":skull: Killed",
    "RUNNING": ":arrows_counterclockwise: Running",
    "STARTING": ":arrows_counterclockwise: Starting",
}


def _md_status_indicator(
    status: str,
    suffix: str | None,
    suffix_type: str | None,
) -> str:
    """Map a status/suffix combination to a human-readable emoji string."""
    # Suffix type takes priority when it carries meaningful semantics
    if suffix_type and suffix_type in _SUFFIX_EMOJI:
        emoji = _SUFFIX_EMOJI[suffix_type]
        label = suffix or status
        return f"{emoji} {label}"
    # Fall back to status-based mapping
    return _STATUS_EMOJI.get(status, status)


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Build a markdown table (returns lines)."""
    lines: list[str] = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def _md_patch(
    cs: Patch,  # type: ignore[name-defined]  # noqa: F821
    *,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
    heading: str | None = None,
) -> list[str]:
    """Render a single Patch as markdown lines."""
    lines: list[str] = []

    # Heading
    display_heading = heading or humanize_cl_name(
        cs.name,
        snapshot=project_display_snapshot,
    )
    lines.append(f"## {display_heading}")
    lines.append("")

    # Metadata line
    meta_parts: list[str] = [f"**Status:** {cs.status}"]
    project = (
        project_display_snapshot.label_for(cs.project_basename)
        if project_display_snapshot is not None
        else cs.project_basename
    )
    meta_parts.append(f"**Project:** {project}")
    if cs.parent:
        meta_parts.append(
            "**Parent:** "
            + humanize_cl_name(
                cs.parent,
                snapshot=project_display_snapshot,
            )
        )
    meta = " · ".join(meta_parts)
    # Bug and PR on same line if present
    extras: list[str] = []
    if cs.bug:
        extras.append(f"**Bug:** {cs.bug}")
    if cs.pr_url:
        extras.append(f"**PR:** {cs.pr_url}")
    if extras:
        meta += " · " + " ".join(extras)
    lines.append(meta)
    lines.append("")

    # Running workspaces
    from sase.running_field import get_claimed_workspaces

    running_claims = get_claimed_workspaces(cs.file_path)
    if running_claims:
        lines.append("### Running Workspaces")
        lines.append("")
        ws_rows: list[list[str]] = []
        for claim in running_claims:
            ws_rows.append(
                [
                    f"#{claim.workspace_num}",
                    str(claim.pid),
                    claim.workflow,
                    humanize_cl_name(
                        claim.cl_name or "",
                        snapshot=project_display_snapshot,
                    ),
                ]
            )
        lines.extend(_md_table(["Workspace", "PID", "Workflow", "Patch"], ws_rows))
        lines.append("")

    # Description as blockquote
    for para_line in cs.description.split("\n"):
        lines.append(f"> {para_line}" if para_line else ">")
    lines.append("")

    if cs.refs:
        lines.append("### References")
        lines.append("")
        lines.extend(f"- `{reference}`" for reference in cs.refs)
        lines.append("")

    # Commits table
    if cs.commits:
        lines.append("### Commits")
        lines.append("")
        rows: list[list[str]] = []
        for entry in cs.commits:
            status_cell = ""
            if entry.suffix_type == "rejected_proposal":
                status_cell = ":warning: Rejected"
            elif entry.proposal_letter:
                status_cell = ":warning: Proposal"
            elif entry.suffix and entry.suffix_type == "error":
                status_cell = f":x: {entry.suffix}"
            rows.append([entry.display_number, entry.note, status_cell])
        lines.extend(_md_table(["#", "Description", "Status"], rows))
        lines.append("")

        # Drawer paths (CHAT/DIFF/PLAN)
        drawer_lines: list[str] = []
        for entry in cs.commits:
            paths: list[str] = []
            if entry.chat:
                paths.append(f"`{entry.chat.replace(str(Path.home()), '~')}`")
            if entry.diff:
                paths.append(f"`{entry.diff.replace(str(Path.home()), '~')}`")
            if entry.plan:
                paths.append(f"`{entry.plan.replace(str(Path.home()), '~')}`")
            if paths:
                drawer_lines.append(
                    f"> **{entry.display_number}:** {' · '.join(paths)}"
                )
        if drawer_lines:
            for dl in drawer_lines:
                lines.append(dl)
            lines.append("")

    # Hooks table (flattened — one row per status line)
    if cs.hooks:
        hook_rows: list[list[str]] = []
        for hook in cs.hooks:
            display_cmd = hook.display_command
            for sl in hook.status_lines or []:
                result = _md_status_indicator(sl.status, sl.suffix, sl.suffix_type)
                duration = sl.duration or ""
                hook_rows.append(
                    [display_cmd, f"#{sl.commit_entry_num}", result, duration]
                )
        if hook_rows:
            lines.append("### Test Hooks")
            lines.append("")
            lines.extend(_md_table(["Hook", "Commit", "Result", "Duration"], hook_rows))
            lines.append("")

    # Comments table
    if cs.comments:
        lines.append("### Review Comments")
        lines.append("")
        comment_rows: list[list[str]] = []
        for comment in cs.comments:
            if comment.suffix and comment.suffix_type == "error":
                status_cell = f":warning: {comment.suffix}"
            elif comment.suffix and comment.suffix_type == "running_agent":
                status_cell = ":arrows_counterclockwise: Running"
            elif comment.suffix:
                status_cell = comment.suffix
            else:
                status_cell = ":white_check_mark:"
            comment_rows.append([comment.reviewer, status_cell])
        lines.extend(_md_table(["Reviewer", "Status"], comment_rows))
        lines.append("")

    # Mentors table (flattened — one row per status line)
    if cs.mentors:
        mentor_rows: list[list[str]] = []
        for mentor in cs.mentors:
            for msl in mentor.status_lines or []:
                result = _md_status_indicator(msl.status, msl.suffix, msl.suffix_type)
                duration = msl.duration or ""
                mentor_rows.append(
                    [
                        f"#{mentor.entry_id}",
                        f"{msl.profile_name} / {msl.mentor_name}",
                        result,
                        duration,
                    ]
                )
        if mentor_rows:
            lines.append("### Mentors")
            lines.append("")
            lines.extend(
                _md_table(["Commit", "Mentor", "Result", "Duration"], mentor_rows)
            )
            lines.append("")

    return lines


def _display_markdown(
    matching: list,  # type: ignore[type-arg]
    *,
    query: str = "",
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
) -> None:
    """Display search results as agent-friendly markdown."""
    from collections import Counter

    from sase.ace.patch import Patch

    patches: list[Patch] = matching
    headings = [
        humanize_cl_name(cs.name, snapshot=project_display_snapshot) for cs in patches
    ]

    # Summary header
    status_counts = Counter(cs.status for cs in patches)
    breakdown = ", ".join(
        f"{count} {status}" for status, count in sorted(status_counts.items())
    )
    print("# Search Results")
    print("")
    if query:
        print(f"**Query:** `{query}`")
        print("")
    print(f"Found {len(patches)} change(s): {breakdown}")
    if len(patches) > 1:
        # Reuse the exact projected heading for link text and destination so
        # display-name substitution cannot make the quick links drift.
        links = " · ".join(f"[{heading}](#{heading})" for heading in headings)
        print("")
        print(links)
    print("")

    # Render each Patch separated by horizontal rules
    for i, (cs, heading) in enumerate(zip(patches, headings, strict=True)):
        if i > 0:
            print("---")
            print("")
        for line in _md_patch(
            cs,
            project_display_snapshot=project_display_snapshot,
            heading=heading,
        ):
            print(line)
