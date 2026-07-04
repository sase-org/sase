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


def append_leader_keycaps(
    text: Text,
    registry: KeymapRegistry,
    action_name: str,
) -> None:
    """Append the configured leader prefix + subkey as adjacent keycaps."""
    key = registry.leader_mode.keys[action_name]
    assert isinstance(key, str)
    append_keycap(text, key_display_name(registry.leader_mode.prefix))
    append_keycap(text, key_display_name(key))
