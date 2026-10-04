"""Both-state coverage for the retired xprompt syntax flag."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.ace.tui.keymaps import load_keymap_registry
from sase.legacy_xprompt_syntax import (
    legacy_xprompt_syntax_enabled,
    normalize_config_layer,
    normalize_keymap_actions,
)


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_macro_config_works_in_both_flag_states(
    enabled: bool,
) -> None:
    layer = {
        "macros": {"a": {"body": "x"}},
        "macro_aliases": {"#a": "#b"},
        "ace": {"prompt_completion": {"auto_macro_menu": False}},
    }
    with override_flags(legacy_xprompt_syntax=enabled):
        canonical, diagnostics = normalize_config_layer(layer)
        assert canonical == layer
        assert diagnostics == []


def test_legacy_config_is_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_xprompt_syntax=True):
        canonical, diagnostics = normalize_config_layer(
            {"xprompts": {"a": {}}}, source="user"
        )
        assert canonical == {"macros": {"a": {}}}
        assert len(diagnostics) == 1
        assert diagnostics[0]["source"] == "user"
        assert diagnostics[0]["path"] == "macros"
        assert diagnostics[0]["kind"] == "retired-alias"
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired; use macros"):
            normalize_config_layer({"xprompts": {"a": {}}})


def test_legacy_aliases_and_nested_keys_normalize_when_enabled() -> None:
    with override_flags(legacy_xprompt_syntax=True):
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


@pytest.mark.parametrize("enabled", [False, True])
def test_both_spellings_collide_in_both_flag_states(enabled: bool) -> None:
    with override_flags(legacy_xprompt_syntax=enabled):
        with pytest.raises(ValueError, match=r"cannot be combined"):
            normalize_config_layer({"xprompts": {"a": {}}, "macros": {"b": {}}})


@pytest.mark.parametrize("value", [None, {}, False, ""])
def test_presence_counts_even_for_empty_values(value: object) -> None:
    with override_flags(legacy_xprompt_syntax=True):
        canonical, _ = normalize_config_layer({"xprompts": value})
        assert "macros" in canonical
        assert "xprompts" not in canonical
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"xprompts is retired"):
            normalize_config_layer({"xprompts": value})


def test_explicit_policy_bit_skips_flag_resolution() -> None:
    """Raw flag-bootstrap readers pass the policy bit without a snapshot."""
    canonical, _ = normalize_config_layer({"xprompts": {"a": {}}}, accept_legacy=True)
    assert canonical == {"macros": {"a": {}}}
    with pytest.raises(ValueError, match=r"xprompts is retired"):
        normalize_config_layer({"xprompts": {"a": {}}}, accept_legacy=False)


def test_raw_layers_stay_raw_before_snapshot_installation() -> None:
    """Flag resolution reads raw layers; normalization never bootstraps it."""
    from sase.config.core import load_config_layers

    layers = load_config_layers()
    assert isinstance(layers, list)
    # The flag snapshot resolves from those raw layers on demand.
    assert legacy_xprompt_syntax_enabled() == current_flags().enabled(
        FeatureFlag.legacy_xprompt_syntax
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_keymap_actions_work_in_both_flag_states(enabled: bool) -> None:
    mapping = {
        "focus_macro": "x",
        "clear_macro_focus": "X",
        "start_last_vcs_macro_in_editor": "ctrl+g",
    }
    with override_flags(legacy_xprompt_syntax=enabled):
        assert normalize_keymap_actions(mapping) == mapping


def test_normalize_keymap_actions_skips_flag_lookup_without_legacy_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> bool:
        raise AssertionError("flag lookup")

    monkeypatch.setattr(
        "sase.legacy_xprompt_syntax.legacy_xprompt_syntax_enabled", boom
    )
    assert normalize_keymap_actions({}) == {}
    assert normalize_keymap_actions({"focus_macro": "x"}) == {"focus_macro": "x"}


def test_legacy_keymap_actions_are_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_xprompt_syntax=True):
        assert normalize_keymap_actions(
            {"focus_xprompt": "x"}, source="ace.keymaps.statistics"
        ) == {"focus_macro": "x"}
        assert normalize_keymap_actions({"clear_xprompt_focus": "X"}) == {
            "clear_macro_focus": "X"
        }
        assert normalize_keymap_actions(
            {"start_last_vcs_xprompt_in_editor": "ctrl+g"}
        ) == {"start_last_vcs_macro_in_editor": "ctrl+g"}
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(
            ValueError, match=r"focus_xprompt is retired; use focus_macro"
        ):
            normalize_keymap_actions({"focus_xprompt": "x"})
        with pytest.raises(
            ValueError, match=r"clear_xprompt_focus is retired; use clear_macro_focus"
        ):
            normalize_keymap_actions({"clear_xprompt_focus": "X"})
        with pytest.raises(
            ValueError,
            match=(
                r"start_last_vcs_xprompt_in_editor is retired; "
                r"use start_last_vcs_macro_in_editor"
            ),
        ):
            normalize_keymap_actions({"start_last_vcs_xprompt_in_editor": "ctrl+g"})


@pytest.mark.parametrize("enabled", [False, True])
def test_both_keymap_spellings_collide_in_both_flag_states(enabled: bool) -> None:
    with override_flags(legacy_xprompt_syntax=enabled):
        with pytest.raises(ValueError, match=r"cannot be combined"):
            normalize_keymap_actions({"focus_xprompt": "x", "focus_macro": "x"})


@pytest.mark.parametrize("value", [None, {}, False, ""])
def test_keymap_presence_counts_even_for_empty_values(value: object) -> None:
    with override_flags(legacy_xprompt_syntax=True):
        canonical = normalize_keymap_actions({"focus_xprompt": value})
        assert "focus_macro" in canonical
        assert "focus_xprompt" not in canonical
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(ValueError, match=r"focus_xprompt is retired"):
            normalize_keymap_actions({"focus_xprompt": value})


def test_legacy_keymap_loader_accepts_alias_when_flag_on() -> None:
    with override_flags(legacy_xprompt_syntax=True):
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


def test_legacy_keymap_loader_rejects_alias_when_flag_off() -> None:
    with override_flags(legacy_xprompt_syntax=False):
        with pytest.raises(
            ValueError, match=r"focus_xprompt is retired; use focus_macro"
        ):
            load_keymap_registry({"keymaps": {"statistics": {"focus_xprompt": "f6"}}})
