"""Shared status/kind style vocabulary for plan CLI detail and search views."""

from __future__ import annotations

import hashlib

# Status icons reuse the bead vocabulary: ◐ in-progress, ✓ done, ○ none/unknown.
STATUS_ICONS = {"wip": "◐", "done": "✓"}
DEFAULT_ICON = "○"
STATUS_STYLES = {"wip": "yellow", "done": "green"}
DEFAULT_STATUS_STYLE = "dim"

KIND_STYLES = {
    "tale": "cyan",
    "epic": "magenta",
    "local": "bright_black",
}
DOCUMENT_KIND_STYLES = (
    "green",
    "yellow",
    "blue",
    "red",
    "bright_cyan",
    "bright_magenta",
    "bright_green",
    "bright_blue",
)


def status_icon(status: str) -> str:
    return STATUS_ICONS.get(status, DEFAULT_ICON)


def status_style(status: str) -> str:
    return STATUS_STYLES.get(status, DEFAULT_STATUS_STYLE)


def kind_style(kind: str) -> str:
    fixed = KIND_STYLES.get(kind)
    if fixed is not None:
        return fixed
    digest = hashlib.sha256(kind.encode("utf-8")).digest()
    return DOCUMENT_KIND_STYLES[
        int.from_bytes(digest[:2], "big") % len(DOCUMENT_KIND_STYLES)
    ]


__all__ = [
    "DEFAULT_ICON",
    "DEFAULT_STATUS_STYLE",
    "DOCUMENT_KIND_STYLES",
    "KIND_STYLES",
    "STATUS_ICONS",
    "STATUS_STYLES",
    "kind_style",
    "status_icon",
    "status_style",
]
