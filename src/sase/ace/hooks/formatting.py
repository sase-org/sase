"""Hook field formatting for ChangeSpec project files."""

from ..changespec import (
    HookEntry,
    is_error_suffix,
    is_running_agent_suffix,
    parse_commit_entry_id,
)
from .timestamps import format_timestamp_display


_CHANGESPEC_FIELD_HEADERS = (
    "NAME:",
    "DESCRIPTION:",
    "STATUS:",
    "HOOKS:",
    "COMMITS:",
    "COMMENTS:",
    "MENTORS:",
    "KICKSTART:",
    "TEST TARGETS:",
)


def _is_field_header(line: str) -> bool:
    """Check if a line is a known ChangeSpec field header."""
    return any(line.startswith(header) for header in _CHANGESPEC_FIELD_HEADERS)


def format_hooks_field(hooks: list[HookEntry]) -> list[str]:
    """Format hooks as lines for the HOOKS field.

    Args:
        hooks: List of HookEntry objects.

    Returns:
        List of formatted lines including "HOOKS:\\n" header.
    """
    if not hooks:
        return []

    # Lazy import to avoid circular dependency
    from .test_targets import contract_test_target_command

    lines = ["HOOKS:\n"]
    for hook in hooks:
        # Contract test target commands to shorthand format
        display_command = contract_test_target_command(hook.command)
        lines.append(f"  {display_command}\n")
        # Output all status lines, sorted by history entry ID (e.g., "1", "1a", "2")
        if hook.status_lines:
            sorted_status_lines = sorted(
                hook.status_lines,
                key=lambda sl: parse_commit_entry_id(sl.commit_entry_num),
            )
            for sl in sorted_status_lines:
                ts_display = format_timestamp_display(sl.timestamp)
                # Build the line parts
                line_parts = [
                    f"      | ({sl.commit_entry_num}) {ts_display} {sl.status}"
                ]
                if sl.duration:
                    line_parts.append(f" ({sl.duration})")
                # Check for suffix (including empty string with running_agent type)
                # or summary (compound suffix format)
                has_suffix = sl.suffix is not None and (
                    sl.suffix
                    or sl.suffix_type
                    in ("running_agent", "summarize_complete", "metahook_complete")
                )
                has_summary_only = sl.summary and not has_suffix
                if has_suffix or has_summary_only:
                    # Build suffix content based on suffix_type
                    suffix_content = ""
                    if has_suffix:
                        # Use suffix_type if available, fall back to message-based detection
                        # "plain" and "summarize_complete" mean no prefix
                        suffix_val = sl.suffix or ""
                        if sl.suffix_type == "plain":
                            suffix_content = suffix_val
                        elif sl.suffix_type == "summarize_complete":
                            suffix_content = f"%: {suffix_val}" if suffix_val else "%"
                        elif sl.suffix_type == "error" or (
                            sl.suffix_type is None and is_error_suffix(sl.suffix)
                        ):
                            suffix_content = f"!: {suffix_val}"
                        elif sl.suffix_type == "running_agent" or (
                            sl.suffix_type is None
                            and is_running_agent_suffix(sl.suffix)
                        ):
                            # Empty suffix → "@", non-empty → "@: msg"
                            suffix_content = f"@: {suffix_val}" if suffix_val else "@"
                        elif sl.suffix_type == "killed_agent":
                            suffix_content = f"~@: {suffix_val}"
                        elif sl.suffix_type == "running_process":
                            suffix_content = f"$: {suffix_val}"
                        elif sl.suffix_type == "pending_dead_process":
                            suffix_content = f"?$: {suffix_val}"
                        elif sl.suffix_type == "killed_process":
                            suffix_content = f"~$: {suffix_val}"
                        elif sl.suffix_type == "metahook_complete":
                            suffix_content = (
                                f"!: metahook | {suffix_val}"
                                if suffix_val
                                else "!: metahook"
                            )
                        else:
                            suffix_content = suffix_val

                    # Append summary if present (compound suffix format)
                    if sl.summary:
                        if suffix_content:
                            suffix_content = f"{suffix_content} | {sl.summary}"
                        else:
                            suffix_content = sl.summary

                    # Sanitize: collapse any newlines to spaces so status
                    # lines stay on a single line in the file
                    suffix_content = " ".join(suffix_content.split())
                    line_parts.append(f" - ({suffix_content})")
                line_parts.append("\n")
                lines.append("".join(line_parts))

    return lines


def apply_hooks_update(
    lines: list[str],
    changespec_name: str,
    hooks: list[HookEntry],
) -> list[str]:
    """Apply HOOKS field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        hooks: List of HookEntry objects to write.

    Returns:
        Updated lines with HOOKS field modified.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    found_hooks = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            was_in_target = in_target_changespec
            in_target_changespec = current_name == changespec_name

            # If we were in target and didn't find HOOKS, insert before NAME
            if was_in_target and not found_hooks and hooks:
                updated_lines.extend(format_hooks_field(hooks))
                found_hooks = True

            updated_lines.append(line)
            i += 1
            continue

        # If we're in the target ChangeSpec
        if in_target_changespec:
            # Check for HOOKS field
            if line.startswith("HOOKS:"):
                found_hooks = True
                # Skip old HOOKS content and write new content
                updated_lines.extend(format_hooks_field(hooks))
                i += 1
                # Skip old hooks content
                while i < len(lines):
                    next_line = lines[i]
                    stripped = next_line.strip()

                    # Check if we've exited the HOOKS section:
                    # - Known field headers end the section
                    # - Two consecutive blank lines end the ChangeSpec
                    if _is_field_header(next_line) or (
                        stripped == ""
                        and i + 1 < len(lines)
                        and lines[i + 1].strip() == ""
                    ):
                        break

                    # Known HOOKS content patterns - skip them
                    if next_line.startswith("      | ") and (
                        stripped[2:].startswith("(") if len(stripped) > 2 else False
                    ):
                        # Status line
                        i += 1
                    elif (
                        next_line.startswith("  ")
                        and not next_line.startswith("    ")
                        and stripped
                        and not stripped.startswith("(")
                        and not stripped.startswith("[")
                    ):
                        # Command line (2-space indented, not 4-space, not empty)
                        i += 1
                    else:
                        # Unrecognized line within HOOKS section (corrupt/orphaned
                        # text from multi-line suffixes) - skip it
                        i += 1
                continue

            # Check for end of ChangeSpec (another field or 2 blank lines)
            if line.strip() == "":
                next_idx = i + 1
                if next_idx < len(lines) and lines[next_idx].strip() == "":
                    # Two blank lines = end of ChangeSpec
                    if not found_hooks and hooks:
                        updated_lines.extend(format_hooks_field(hooks))
                        found_hooks = True

        updated_lines.append(line)
        i += 1

    # If we reached end of file while still in target changespec
    if in_target_changespec and not found_hooks and hooks:
        updated_lines.extend(format_hooks_field(hooks))

    return updated_lines
