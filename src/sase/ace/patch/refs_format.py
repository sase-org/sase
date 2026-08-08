"""Formatting helpers for the ChangeSpec REFS field."""


def format_refs_field(refs: list[str] | tuple[str, ...]) -> list[str]:
    """Format canonical artifact references as a ChangeSpec section."""

    if not refs:
        return []
    return ["REFS:\n", *(f"  {reference}\n" for reference in refs)]


__all__ = ["format_refs_field"]
