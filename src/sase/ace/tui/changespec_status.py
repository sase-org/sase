"""Shared ChangeSpec status glyph and color conventions."""

from __future__ import annotations


def changespec_status_glyph(status: str) -> tuple[str, str]:
    """Return the ChangeSpecs-tab glyph and natural color for *status*."""
    if status.casefold() == "unknown":
        return "?", "#808080"
    if "..." in status:
        return "~", "#87AFFF"
    if status.startswith("Draft"):
        return "D", "#FFD700"
    if status.startswith("Ready"):
        return "R", "#87D700"
    if status.startswith("Mailed"):
        return "M", "#00D787"
    if status.startswith("Submitted"):
        return "S", "#00AF00"
    if status.startswith("Reverted"):
        return "X", "#808080"
    if status.startswith("Archived"):
        return "A", "#606060"
    return "W", "#87CEEB"


__all__ = ["changespec_status_glyph"]
