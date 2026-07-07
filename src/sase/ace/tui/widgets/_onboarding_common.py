"""Shared Rich text helpers for ACE onboarding panels."""

from __future__ import annotations

from rich.text import Text

from ..keymaps import KeymapRegistry, key_display_name


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


def leader_key_sequence_display(registry: KeymapRegistry, action_name: str) -> str:
    """Return the configured leader-mode sequence for *action_name*."""
    key = registry.leader_mode.keys[action_name]
    assert isinstance(key, str)
    return key_sequence_display(registry.leader_mode.prefix, key)


def _guide_footer_key_display(key: str) -> str:
    display = key_display_name(key)
    if display in {"Tab", "Shift+Tab"}:
        return display.lower()
    return display


def build_guide_footer(registry: KeymapRegistry) -> Text:
    text = Text(justify="center")
    text.append("esc closes · ", style="dim italic")
    text.append(_guide_footer_key_display(registry.app.next_tab), style="dim")
    text.append(" / ", style="dim italic")
    text.append(_guide_footer_key_display(registry.app.prev_tab), style="dim")
    text.append(" other tabs' guides · ", style="dim italic")
    text.append(leader_key_sequence_display(registry, "tab_guide"), style="dim")
    text.append(" reopens anytime", style="dim italic")
    return text
