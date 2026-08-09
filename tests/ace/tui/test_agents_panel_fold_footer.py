"""Footer binding tests for Agents-tab fold mode."""

from unittest.mock import patch

import pytest

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.fold_scale import (
    CLAN_FOLD_SCALE,
    FAMILY_FOLD_SCALE,
    TRIBE_FOLD_SCALE,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets import KeybindingFooter


def test_agents_fold_footer_uses_nested_agent_submap() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(
            current_tab="agents",
            fold_scale=CLAN_FOLD_SCALE,
        )

    assert update.call_args.args == (
        [
            ("1", "level 1"),
            ("2", "level 2"),
            ("3", "level 3"),
            ("z", "level forward"),
            ("Z", "toggle all"),
            ("a", "section forward"),
            ("A", "toggle section"),
        ],
    )
    assert update.call_args.kwargs == {"mode_label": "FOLD"}


@pytest.mark.parametrize(
    ("scale", "direct_keys"),
    [
        (FAMILY_FOLD_SCALE, ["1", "2"]),
        (CLAN_FOLD_SCALE, ["1", "2", "3"]),
        (TRIBE_FOLD_SCALE, ["1", "2", "3", "4"]),
    ],
)
def test_agents_fold_footer_direct_hints_match_active_scale(
    scale: tuple[FoldLevel, ...],
    direct_keys: list[str],
) -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(current_tab="agents", fold_scale=scale)

    bindings = update.call_args.args[0]
    assert [key for key, _label in bindings[: len(scale)]] == direct_keys


def test_fold_footer_uses_configured_direct_subkeys_in_each_context() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {
                            "set_level_2": "w",
                            "agents": {"set_level_3": "e"},
                        }
                    }
                }
            }
        }
    )
    footer = KeybindingFooter()
    footer.set_keymap_registry(registry)

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(
            current_tab="agents",
            fold_scale=CLAN_FOLD_SCALE,
        )
    assert update.call_args.args[0][:3] == [
        ("1", "level 1"),
        ("2", "level 2"),
        ("e", "level 3"),
    ]

    with patch.object(footer, "_update_display") as update:
        footer.update_fold_bindings(current_tab="patches")
    assert update.call_args.args[0][:3] == [
        ("1", "level 1"),
        ("w", "level 2"),
        ("3", "level 3"),
    ]
