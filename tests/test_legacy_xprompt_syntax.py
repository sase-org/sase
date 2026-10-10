"""Unconditional coverage for the retired xprompt syntax aliases."""

from __future__ import annotations

import pytest

from sase.ace.tui.keymaps import load_keymap_registry
from sase.legacy_xprompt_syntax import (
    normalize_config_layer,
    normalize_keymap_actions,
)


def test_canonical_macro_config_passes_through_untouched() -> None:
    layer = {
        "macros": {"a": {"body": "x"}},
        "macro_aliases": {"#a": "#b"},
        "ace": {"prompt_completion": {"auto_macro_menu": False}},
    }
    canonical, diagnostics = normalize_config_layer(layer)
    assert canonical == layer
    assert diagnostics == []


def test_legacy_config_is_always_an_accepted_alias() -> None:
    canonical, diagnostics = normalize_config_layer(
        {"xprompts": {"a": {}}}, source="user"
    )
    assert canonical == {"macros": {"a": {}}}
    assert len(diagnostics) == 1
    assert diagnostics[0]["source"] == "user"
    assert diagnostics[0]["path"] == "macros"
    assert diagnostics[0]["kind"] == "retired-alias"


def test_legacy_aliases_and_nested_keys_normalize() -> None:
    canonical, diagnostics = normalize_config_layer(
        {
            "xprompt_aliases": {"#a": "#b"},
            "ace": {
                "prompt_completion": {"auto_xprompt_menu": True},
                "prompt_inputs": {"xprompt_placeholder_args": False},
            },
            "mentor_profiles": [
                {"mentors": [{"xprompt": "#a"}, {"macro": "#b"}]},
            ],
        }
    )
    assert canonical == {
        "macro_aliases": {"#a": "#b"},
        "ace": {
            "prompt_completion": {"auto_macro_menu": True},
            "prompt_inputs": {"macro_placeholder_args": False},
        },
        "mentor_profiles": [
            {"mentors": [{"macro": "#a"}, {"macro": "#b"}]},
        ],
    }
    assert len(diagnostics) == 4


def test_both_spellings_collide() -> None:
    with pytest.raises(ValueError, match=r"cannot be combined"):
        normalize_config_layer({"xprompts": {"a": {}}, "macros": {"b": {}}})


@pytest.mark.parametrize("value", [None, {}, False, ""])
def test_presence_counts_even_for_empty_values(value: object) -> None:
    canonical, _ = normalize_config_layer({"xprompts": value})
    assert "macros" in canonical
    assert "xprompts" not in canonical


def test_retired_policy_bit_is_accepted_and_ignored() -> None:
    """The retired switch no longer changes policy: both values accept."""
    for accept_legacy in (True, False):
        canonical, _ = normalize_config_layer(
            {"xprompts": {"a": {}}}, accept_legacy=accept_legacy
        )
        assert canonical == {"macros": {"a": {}}}


def test_raw_layers_normalize_without_flag_resolution() -> None:
    """Normalization needs no flag snapshot since the switch retired."""
    from sase.config.core import load_config_layers

    layers = load_config_layers()
    assert isinstance(layers, list)
    canonical, _ = normalize_config_layer({"xprompts": {"a": {}}})
    assert canonical == {"macros": {"a": {}}}


def test_canonical_keymap_actions_pass_through_untouched() -> None:
    mapping = {
        "focus_macro": "x",
        "clear_macro_focus": "X",
        "start_last_vcs_macro_in_editor": "ctrl+g",
    }
    assert normalize_keymap_actions(mapping) == mapping


def test_keymap_normalization_needs_no_flag_lookup() -> None:
    assert normalize_keymap_actions({}) == {}
    assert normalize_keymap_actions({"focus_macro": "x"}) == {"focus_macro": "x"}


def test_legacy_keymap_actions_are_always_accepted_aliases() -> None:
    assert normalize_keymap_actions(
        {"focus_xprompt": "x"}, source="ace.keymaps.statistics"
    ) == {"focus_macro": "x"}
    assert normalize_keymap_actions({"clear_xprompt_focus": "X"}) == {
        "clear_macro_focus": "X"
    }
    assert normalize_keymap_actions({"start_last_vcs_xprompt_in_editor": "ctrl+g"}) == {
        "start_last_vcs_macro_in_editor": "ctrl+g"
    }


def test_both_keymap_spellings_collide() -> None:
    with pytest.raises(ValueError, match=r"cannot be combined"):
        normalize_keymap_actions({"focus_xprompt": "x", "focus_macro": "x"})


@pytest.mark.parametrize("value", [None, {}, False, ""])
def test_keymap_presence_counts_even_for_empty_values(value: object) -> None:
    canonical = normalize_keymap_actions({"focus_xprompt": value})
    assert "focus_macro" in canonical
    assert "focus_xprompt" not in canonical


def test_legacy_keymap_loader_accepts_alias() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {"focus_xprompt": "f6"},
                "app": {"start_last_vcs_xprompt_in_editor": "f7"},
            }
        }
    )
    assert registry.statistics.focus_macro == "f6"
    assert registry.app.start_last_vcs_macro_in_editor == "f7"
