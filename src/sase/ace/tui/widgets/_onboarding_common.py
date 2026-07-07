"""Shared Rich text helpers for ACE onboarding panels."""

from __future__ import annotations

from rich.text import Text

from ..keymaps import key_display_name


def append_keycap(text: Text, label: str) -> None:
    text.append(" ")
    text.append(f" {label} ", style="bold #1a1a1a on #00D7AF")
    text.append(" ")


def append_section_heading(text: Text, label: str, *, accent: str) -> None:
    text.append(label, style=f"bold {accent}")
    text.append("\n")


def append_doc_link(text: Text, url: str, description: str, *, accent: str) -> None:
    text.append(url, style=f"bold {accent} link {url}")
    text.append(" ")
    text.append(description, style="dim")
    text.append("\n")


def key_sequence_display(*keys: str) -> str:
    """Format a prefix-key sequence for readable prose."""
    parts = [key_display_name(key) for key in keys]
    if all(len(part) == 1 for part in parts):
        return "".join(parts)
    if len(parts) == 2 and len(parts[1]) == 1 and not parts[1].isalnum():
        return "".join(parts)
    return " ".join(parts)
