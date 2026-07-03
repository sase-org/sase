"""Shared Rich text helpers for ACE onboarding panels."""

from __future__ import annotations

from rich.text import Text


def append_keycap(text: Text, label: str) -> None:
    text.append(" ")
    text.append(f" {label} ", style="bold #1a1a1a on #00D7AF")
    text.append(" ")


def append_section_heading(text: Text, label: str, *, accent: str) -> None:
    text.append(label, style=f"bold {accent}")
    text.append("\n")
