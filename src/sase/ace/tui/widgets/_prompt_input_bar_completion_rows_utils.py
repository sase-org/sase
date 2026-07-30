"""Shared helpers for prompt input completion rows."""


def truncate_cell(value: str, width: int) -> str:
    """Truncate a value to a fixed-width completion row cell."""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3].rstrip() + "..."
