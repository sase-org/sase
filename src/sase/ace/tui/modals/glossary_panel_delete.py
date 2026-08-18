"""Delete confirmation copy and neighbor reselect for the Glossary panel."""

from __future__ import annotations

from collections.abc import Sequence


def build_glossary_delete_subject(
    *,
    term: str,
    aliases: Sequence[str],
    definition: str,
    config_path: str | None,
    referenced_by: Sequence[str],
) -> str:
    """Build the confirm-dialog subject for deleting *term*."""
    first_line = next(
        (line.strip() for line in definition.splitlines() if line.strip()),
        "",
    )
    inbound = tuple(referenced_by)
    if len(inbound) == 1:
        inbound_line = f"1 definition references this term: {inbound[0]}"
    elif inbound:
        inbound_line = (
            f"{len(inbound)} definitions reference this term: {', '.join(inbound)}"
        )
    else:
        inbound_line = "0 definitions reference this term"
    lines = [
        f"Term: {term}",
        f"Aliases: {', '.join(aliases) if aliases else '(none)'}",
        f"Definition: {first_line or '(empty)'}",
    ]
    if config_path:
        lines.append(f"Config: {config_path}")
    lines.append(inbound_line)
    return "\n".join(lines)


def neighbor_term_after_delete(terms: Sequence[str], deleted_term: str) -> str | None:
    """Return the term that should stay selected after *deleted_term* is removed.

    That is the row that takes the deleted term's index, or the last remaining
    row when the deleted term was last.
    """
    visible = list(terms)
    try:
        index = visible.index(deleted_term)
    except ValueError:
        return visible[-1] if visible else None
    remaining = [term for term in visible if term != deleted_term]
    if not remaining:
        return None
    if index >= len(remaining):
        return remaining[-1]
    return remaining[index]


__all__ = [
    "build_glossary_delete_subject",
    "neighbor_term_after_delete",
]
