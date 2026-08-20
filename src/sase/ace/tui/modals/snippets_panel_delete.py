"""Delete confirmation copy and neighbor reselect for the Snippets panel."""

from __future__ import annotations

from collections.abc import Sequence

from sase.snippet.models import SnippetEntry, SnippetSourceContribution

_MUTABLE_KINDS = frozenset({"user", "overlay", "project", "configured"})


def snippet_entry_is_mutable(entry: SnippetEntry | None) -> bool:
    """Return whether *entry*'s winning definition can be edited or deleted."""
    if entry is None:
        return False
    origin = entry.origin
    return bool(origin.writable and origin.kind in _MUTABLE_KINDS and origin.path)


def build_snippet_delete_subject(entry: SnippetEntry) -> str:
    """Build the confirm-dialog subject for deleting *entry*."""
    inbound = entry.relations.inbound
    if len(inbound) == 1:
        inbound_line = f"1 snippet calls this trigger: {inbound[0]}"
    elif inbound:
        inbound_line = (
            f"{len(inbound)} snippets call this trigger: {', '.join(inbound)}"
        )
    else:
        inbound_line = "0 snippets call this trigger"
    source = entry.origin.display_path or entry.origin.path or entry.origin.kind
    first_line = next(
        (line for line in entry.raw_template.splitlines() if line.strip()),
        "",
    )
    revealed = _revealed_source(entry)
    lines = [
        f"Trigger: {entry.trigger}",
        f"File: {source}",
        f"Template: {first_line or '(empty)'}",
        inbound_line,
    ]
    if revealed is not None:
        revealed_label = revealed.display_path or revealed.path or revealed.kind
        lines.append(f"Reveals: {revealed_label}")
    else:
        lines.append("Reveals: (none)")
    return "\n".join(lines)


def neighbor_trigger_after_delete(
    triggers: Sequence[str], deleted_trigger: str
) -> str | None:
    """Return the trigger that should stay selected after a delete."""
    visible = list(triggers)
    try:
        index = visible.index(deleted_trigger)
    except ValueError:
        return visible[-1] if visible else None
    remaining = [trigger for trigger in visible if trigger != deleted_trigger]
    if not remaining:
        return None
    if index >= len(remaining):
        return remaining[-1]
    return remaining[index]


def _revealed_source(entry: SnippetEntry) -> SnippetSourceContribution | None:
    origin_path = entry.origin.path or ""
    kept = [item for item in entry.contributions if (item.path or "") != origin_path]
    if not kept:
        return None
    return kept[-1]


__all__ = [
    "build_snippet_delete_subject",
    "neighbor_trigger_after_delete",
    "snippet_entry_is_mutable",
]
