"""Both-state coverage for the retired xprompt syntax flag."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.legacy_xprompt_syntax import (
    legacy_xprompt_syntax_enabled,
    normalize_config_layer,
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
