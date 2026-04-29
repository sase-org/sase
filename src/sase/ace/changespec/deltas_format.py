"""DELTAS field formatting for ChangeSpec project files."""

from .models import DeltaEntry


_TYPE_TO_GLYPH = {"A": "+", "M": "~", "D": "-"}


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
    return lines
