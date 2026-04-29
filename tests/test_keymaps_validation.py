"""Tests for keymap validation (duplicate keys, invalid keys)."""

import logging

import pytest

from sase.ace.tui.keymaps import is_valid_key, load_keymap_registry


# --- is_valid_key ---


def test_single_char_keys_accepted() -> None:
    """Single alphanumeric characters are valid keys."""
    assert is_valid_key("j")
    assert is_valid_key("Q")
    assert is_valid_key("1")


def test_valid_named_keys_accepted() -> None:
    """Named Textual keys and modifier combos are valid."""
    assert is_valid_key("full_stop")
    assert is_valid_key("ctrl+d")
    assert is_valid_key("escape")
    assert is_valid_key("shift+tab")
    assert is_valid_key("enter")
    assert is_valid_key("f12")


def test_compound_key_alternatives_accepted() -> None:
    """Comma-separated Textual binding alternatives are valid."""
    assert is_valid_key("colon,semicolon")
    assert is_valid_key("ctrl+d,shift+tab")


def test_compound_key_with_invalid_alternative_rejected() -> None:
    """Every segment of a compound binding must be a valid key."""
    assert not is_valid_key("colon,not_a_real_key")
    assert not is_valid_key("colon,")
    assert not is_valid_key("colon,colon")


def test_empty_string_key_invalid() -> None:
    """Empty string is not a valid key and reverts to default."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": ""}}})
    assert reg.app.next_changespec == "j"  # default


def test_invalid_key_reverts_to_default() -> None:
    """Nonsense key name reverts to default."""
    reg = load_keymap_registry(
        {"keymaps": {"app": {"next_changespec": "not_a_real_key"}}}
    )
    assert reg.app.next_changespec == "j"


def test_invalid_key_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid key triggers a log warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry(
            {"keymaps": {"app": {"next_changespec": "not_a_real_key"}}}
        )
    assert any("Invalid key" in r.message for r in caplog.records)


# --- Duplicate key detection ---


def test_duplicate_app_keys_reverts_to_default() -> None:
    """Override that conflicts with a default key reverts."""
    # next_changespec overridden to "q" clashes with quit's default "q".
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "q"}}})
    assert reg.app.next_changespec == "j"  # reverted to default
    assert reg.app.quit == "q"  # unchanged


def test_duplicate_app_keys_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Duplicate key conflict triggers a log warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry({"keymaps": {"app": {"next_changespec": "q"}}})
    assert any("Duplicate key" in r.message for r in caplog.records)


def test_both_overrides_duplicate_revert_both() -> None:
    """Two user overrides mapping to the same key both revert."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "next_changespec": "Z",
                    "prev_changespec": "Z",
                },
            },
        }
    )
    assert reg.app.next_changespec == "j"  # default
    assert reg.app.prev_changespec == "k"  # default


def test_compound_key_conflict_reverts_override() -> None:
    """A key inside a compound binding conflicts like a normal app key."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "semicolon"}}})
    assert reg.app.open_command_palette == "colon,semicolon"
    assert reg.app.next_changespec == "j"


def test_compound_key_conflict_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Compound-key duplicate conflicts emit the existing duplicate warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry({"keymaps": {"app": {"next_changespec": "semicolon"}}})
    assert any("Duplicate key" in r.message for r in caplog.records)


def test_custom_mode_prefix_conflicts_with_compound_app_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Custom mode prefixes compare against each key in a compound app binding."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "my_mode": {
                            "prefix": "semicolon",
                            "keys": {
                                "do_thing": {
                                    "key": "t",
                                    "shell": "echo hi",
                                },
                            },
                        },
                    },
                }
            }
        )
    assert any("prefix 'semicolon' conflicts" in r.message for r in caplog.records)
