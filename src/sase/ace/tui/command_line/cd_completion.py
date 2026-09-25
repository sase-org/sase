"""In-memory ``cd`` completion for the ``:`` Command Line."""

from __future__ import annotations

from typing import Any, cast

from sase.ace.tui.command_line.sources import path_completion_request
from sase.completion.command_line_grammar import LineContext

__all__ = [
    "cd_completion_context",
    "complete_cd",
    "path_request_for_slot",
    "source_key_for_slot",
]


def cd_completion_context(line: str, cursor: int) -> LineContext | None:
    """Resolve the ``cd`` built-in's single completion slot in memory."""
    before_cursor = line[:cursor]
    leading = len(before_cursor) - len(before_cursor.lstrip())
    command_end = leading + 2
    if before_cursor[leading:command_end] != "cd":
        return None
    if len(before_cursor) == command_end:
        return None
    if not before_cursor[command_end].isspace():
        return None
    replace_start = command_end
    while replace_start < len(before_cursor) and before_cursor[replace_start].isspace():
        replace_start += 1
    token = before_cursor[replace_start:]
    # ``cd`` accepts exactly one argument.  Leave editing later text to the
    # normal input rather than replacing a surprising span.
    if any(char.isspace() for char in token):
        return None
    value_kind = "project" if token.startswith("+") else "dir"
    return cast(
        LineContext,
        {
            "builtin": "cd",
            "path": ["cd"],
            "argv": ["cd", token],
            "slot": {
                "value_kind": value_kind,
                "replace_start": replace_start,
                "replace_end": cursor,
            },
        },
    )


def _slot_prefix(line: str, cursor: int, context: LineContext) -> str:
    """Return the current slot text without resolving or touching disk."""
    slot = context.get("slot") or {}
    try:
        start = int(slot.get("replace_start", cursor))
    except (TypeError, ValueError):
        start = cursor
    return line[max(0, min(start, cursor)) : max(0, cursor)]


def path_request_for_slot(
    line: str, cursor: int, context: LineContext, cwd: str
) -> Any | None:
    """Build the pure path scan request for a path/dir slot, if applicable."""
    slot = context.get("slot") or {}
    value_kind = str(slot.get("value_kind") or "")
    if value_kind not in {"path", "dir"}:
        return None
    return path_completion_request(_slot_prefix(line, cursor, context), cwd)


def source_key_for_slot(
    line: str, cursor: int, context: LineContext, cwd: str
) -> str | None:
    """Return a directory-specific cache key for native path rows."""
    request = path_request_for_slot(line, cursor, context, cwd)
    return None if request is None else request.source_key


def complete_cd(
    line: str,
    cursor: int,
    context: LineContext,
    dynamic: list[dict[str, Any]],
) -> dict[str, Any]:
    """Render ``cd``'s directory, project, and unpin candidates."""
    slot = context.get("slot") or {}
    value_kind = str(slot.get("value_kind") or "dir")
    typed = _slot_prefix(line, cursor, context)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in dynamic:
        raw_value = str(candidate.get("value", "") or "")
        if not raw_value:
            continue
        insert = f"+{raw_value}" if value_kind == "project" else raw_value
        if not insert.casefold().startswith(typed.casefold()) or insert in seen:
            continue
        seen.add(insert)
        items.append(
            {
                "insert_text": insert,
                "display": str(candidate.get("display") or insert),
                "description": str(candidate.get("description") or ""),
                "badge": str(candidate.get("badge") or value_kind),
                "source": str(candidate.get("source") or "provider"),
                "match_runs": [],
                "selected": False,
            }
        )
    if value_kind == "dir" and "-".startswith(typed):
        # Last, so an empty-argument Tab lands on a directory, not on unpin.
        items.append(
            {
                "insert_text": "-",
                "display": "-",
                "description": "unpin and follow the TUI project",
                "badge": "dir",
                "source": "builtin",
                "match_runs": [],
                "selected": False,
            }
        )
    return {
        "items": items,
        "total": len(items),
        "kind": value_kind,
        "replace_start": int(slot.get("replace_start", cursor)),
        "replace_end": int(slot.get("replace_end", cursor)),
    }
