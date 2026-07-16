"""Hint parsing utilities for TUI.

This module provides functions to parse hint input from users.
"""

import os
from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True)
class _NumericHintSelection:
    """Parsed positive numeric hints with actionable diagnostics.

    ``numbers`` preserves first-seen order and removes overlaps.  Tokens that
    are not positive integers or inclusive ascending ranges are reported in
    ``malformed``; syntactically valid numbers absent from ``available`` are
    reported separately in ``unavailable``.
    """

    numbers: tuple[int, ...] = ()
    malformed: tuple[str, ...] = ()
    unavailable: tuple[int, ...] = ()


def parse_numeric_hint_selection(
    user_input: str,
    available: Collection[int] | None = None,
) -> _NumericHintSelection:
    """Parse whitespace-delimited positive numbers and ascending ranges."""
    available_set = set(available) if available is not None else None
    numbers: list[int] = []
    malformed: list[str] = []
    unavailable: list[int] = []
    seen_numbers: set[int] = set()
    seen_malformed: set[str] = set()
    seen_unavailable: set[int] = set()

    for token in user_input.split():
        expanded: range | tuple[int, ...]
        if token.count("-") == 1 and not token.startswith("-"):
            start_text, end_text = token.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                expanded = ()
            else:
                start = int(start_text)
                end = int(end_text)
                expanded = range(start, end + 1) if 0 < start <= end else ()
        elif token.isdigit() and int(token) > 0:
            expanded = (int(token),)
        else:
            expanded = ()

        if not expanded:
            if token not in seen_malformed:
                malformed.append(token)
                seen_malformed.add(token)
            continue

        for number in expanded:
            if available_set is not None and number not in available_set:
                if number not in seen_unavailable:
                    unavailable.append(number)
                    seen_unavailable.add(number)
                continue
            if number not in seen_numbers:
                numbers.append(number)
                seen_numbers.add(number)

    return _NumericHintSelection(
        numbers=tuple(numbers),
        malformed=tuple(malformed),
        unavailable=tuple(unavailable),
    )


def _expand_hint_part(part: str) -> list[int]:
    """Expand a hint part which may be a single number or a range.

    Args:
        part: A string like "5" or "1-10"

    Returns:
        List of integers (empty if invalid)
    """
    parsed = parse_numeric_hint_selection(part)
    if parsed.malformed:
        return []
    return list(parsed.numbers)


def _is_valid_hint_part(part: str) -> bool:
    """Check if a hint part is valid (single number or range).

    Args:
        part: A string like "5" or "1-10"

    Returns:
        True if the part is a valid hint (number or range)
    """
    return bool(_expand_hint_part(part))


def is_rerun_input(user_input: str) -> bool:
    """Check if user input is a rerun/delete command (list of integers/ranges with optional suffix).

    Suffixes:
        - No suffix: rerun the hook (clear status for last history entry)
        - '@' suffix: delete the hook entirely

    Args:
        user_input: The user's input string

    Returns:
        True if input looks like a rerun command (e.g., "1 2 3", "1@", "2@ 3", "1-5")
    """
    if not user_input:
        return False

    for part in user_input.split():
        # Reject '@@' suffix (no longer supported)
        if part.endswith("@@"):
            return False
        # Strip optional '@' suffix
        part_stripped = part.rstrip("@")
        # Check if it's a valid integer or range
        if not _is_valid_hint_part(part_stripped):
            return False

    return True


def build_editor_args(editor: str, files: list[str]) -> list[str]:
    """Build editor command arguments.

    Args:
        editor: The editor command (e.g., from $EDITOR)
        files: List of file paths to open

    Returns:
        List of command arguments for subprocess.run
    """
    return [editor] + files


def parse_view_input(
    user_input: str, hint_mappings: dict[int, str]
) -> tuple[list[str], bool, bool, list[int]]:
    """Parse user input for view files modal.

    Args:
        user_input: The user's input string (e.g., "1 2 3@" or "1-5%" or "1-5@")
        hint_mappings: Dict mapping hint numbers to file paths

    Returns:
        Tuple of:
        - List of valid file paths to view/edit/copy
        - Whether to open in editor (@ suffix detected)
        - Whether to copy to clipboard (% suffix detected)
        - List of invalid hint numbers (for error messages)
    """
    parts = user_input.split()
    if not parts:
        return [], False, False, []

    open_in_editor = False
    copy_to_clipboard = False
    files_to_view: list[str] = []
    invalid_hints: list[int] = []

    for part in parts:
        # Check for '@' suffix (open in editor)
        if part.endswith("@"):
            open_in_editor = True
            part = part[:-1]
        # Check for '%' suffix (copy to clipboard)
        elif part.endswith("%"):
            copy_to_clipboard = True
            part = part[:-1]

        # Skip empty parts (standalone '@' or '%' is not supported)
        if not part:
            continue

        # Expand the part (handles both single numbers and ranges)
        parsed = parse_numeric_hint_selection(part, hint_mappings)
        invalid_hints.extend(parsed.unavailable)
        for hint_num in parsed.numbers:
            file_path = os.path.expanduser(hint_mappings[hint_num])
            if file_path not in files_to_view:  # Avoid duplicates
                files_to_view.append(file_path)

    return files_to_view, open_in_editor, copy_to_clipboard, invalid_hints


def parse_edit_hooks_input(
    user_input: str, hint_mappings: dict[int, str]
) -> tuple[list[int], list[int], list[int]]:
    """Parse user input for rerun/delete hooks.

    Args:
        user_input: The user's input string (e.g., "1 2@ 3" or "1-5@")
        hint_mappings: Dict mapping hint numbers to file paths

    Returns:
        Tuple of:
        - List of hint numbers to rerun
        - List of hint numbers to delete
        - List of invalid hint numbers
    """
    hints_to_rerun: list[int] = []
    hints_to_delete: list[int] = []
    invalid_hints: list[int] = []

    for part in user_input.split():
        action = "rerun"
        if part.endswith("@"):
            action = "delete"
            part = part[:-1]

        # Expand the part (handles both single numbers and ranges)
        parsed = parse_numeric_hint_selection(part, hint_mappings)
        invalid_hints.extend(parsed.unavailable)
        for hint_num in parsed.numbers:
            if action == "delete":
                if hint_num not in hints_to_delete:
                    hints_to_delete.append(hint_num)
            else:
                if hint_num not in hints_to_rerun:
                    hints_to_rerun.append(hint_num)

    return hints_to_rerun, hints_to_delete, invalid_hints


def parse_test_targets(test_input: str) -> list[str]:
    """Parse test target input into a list of targets.

    Args:
        test_input: String starting with "//" containing test targets

    Returns:
        List of test targets, each prefixed with "//"
    """
    parts = test_input.split()
    targets = []
    for part in parts:
        part = part.strip()
        if part:
            # Ensure each target starts with "//"
            if not part.startswith("//"):
                part = "//" + part
            targets.append(part)
    return targets
