"""DELTAS field formatting for ChangeSpec project files."""

from .models import DeltaEntry, DeltaLineStats


_TYPE_TO_GLYPH = {"A": "+", "M": "~", "D": "-"}


def _format_delta_line_stats(stats: DeltaLineStats) -> str:
    """Format line stats for the compact on-disk drawer payload."""
    if stats.binary:
        return "binary"

    tokens: list[str] = []
    if stats.added:
        tokens.append(f"+{stats.added}")
    if stats.modified:
        tokens.append(f"~{stats.modified}")
    if stats.removed:
        tokens.append(f"-{stats.removed}")
    return " ".join(tokens) if tokens else "0"


def format_deltas_field(deltas: list[DeltaEntry]) -> list[str]:
    """Format a DELTAS field as on-disk lines.

    Args:
        deltas: List of DeltaEntry objects. An empty list emits nothing.

    Returns:
        List of formatted lines including the ``DELTAS:`` header. Empty list if
        ``deltas`` is empty (the section is omitted from disk in that case).
        Entries are sorted alphabetically by path; change types are mapped to
        their on-disk glyphs (A->+, M->~, D->-).
    """
    if not deltas:
        return []

    lines = ["DELTAS:\n"]
    for entry in sorted(deltas, key=lambda e: e.path):
        glyph = _TYPE_TO_GLYPH[entry.change_type]
        lines.append(f"  {glyph} {entry.path}\n")
        if entry.line_stats is not None:
            lines.append(
                f"      | LINES: {_format_delta_line_stats(entry.line_stats)}\n"
            )
    return lines
