"""Human-readable formatting for configured Textual key names."""

from sase.ace.tui.keymaps.key_validation import (
    UNBOUND_KEY,
    _KEY_DISPLAY,
    canonicalize_single_key,
    split_key_alternatives,
)
from sase.ace.tui.keymaps.types import KeymapRegistry


def key_display_name(textual_key: str) -> str:
    """Convert a Textual key name to a human-readable display string.

    Examples:
        ``"full_stop"`` -> ``"."``
        ``"ctrl+d"`` -> ``"Ctrl+D"``
        ``"j"`` -> ``"j"``
    """
    alternatives = split_key_alternatives(textual_key)
    if not alternatives or alternatives == ("",):
        return ""
    if len(alternatives) > 1:
        return " / ".join(key_display_name(alternative) for alternative in alternatives)
    textual_key = canonicalize_single_key(alternatives[0])
    if textual_key == UNBOUND_KEY:
        return ""
    if textual_key == "ctrl+@":
        return "Ctrl+Space"
    if textual_key in _KEY_DISPLAY:
        return _KEY_DISPLAY[textual_key]
    key_parts = textual_key.split("+")
    modifiers = {"ctrl": "Ctrl", "shift": "Shift"}
    if len(key_parts) > 1 and all(part in modifiers for part in key_parts[:-1]):
        key_name = _KEY_DISPLAY.get(key_parts[-1], key_parts[-1].upper())
        return "+".join([*(modifiers[part] for part in key_parts[:-1]), key_name])
    return textual_key


def leader_key_display(registry: KeymapRegistry, action_name: str) -> str:
    """Format one configured leader chord for display surfaces."""
    subkey = registry.leader_mode.keys[action_name]
    assert isinstance(subkey, str)
    parts = [
        key_display_name(registry.leader_mode.prefix),
        key_display_name(subkey),
    ]
    if all(len(part) == 1 for part in parts):
        return "".join(parts)
    if len(parts[1]) == 1 and not parts[1].isalnum():
        return "".join(parts)
    return " ".join(parts)


def footer_key_display(textual_key: str) -> str:
    """Convert a Textual key name for footer display.

    Multi-character named keys use the footer's angle-bracket convention;
    single characters and modified keys pass through unchanged.
    """
    alternatives = split_key_alternatives(textual_key)
    if len(alternatives) > 1:
        return " / ".join(
            footer_key_display(alternative) for alternative in alternatives
        )
    name = key_display_name(textual_key)
    if len(name) == 1 or name.startswith(("Ctrl+", "Shift+")):
        return name
    return f"<{name.lower()}>"
