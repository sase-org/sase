"""Tests for opening the Models panel from leader mode."""

from typing import cast
from unittest.mock import MagicMock, call

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.modals.models_panel import ModelsPanelResult
from sase.ace.tui.widgets import AliasOverridesIndicator, LLMOverrideIndicator
from tests._temporary_llm_override_helpers import full_registry


def test_leader_handler_dispatches_models_panel() -> None:
    mixin = MagicMock()
    mixin._keymap_registry = full_registry()
    mixin.current_tab = "changespecs"  # legacy tab id
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "m")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_leader_handler_honors_legacy_action_id() -> None:
    """A user keymap still binding the old action id keeps opening the panel."""
    mixin = MagicMock()
    mixin._keymap_registry = full_registry(
        {
            "keymaps": {
                "modes": {"leader_mode": {"keys": {"temporary_llm_override": "z"}}}
            }
        }
    )
    mixin.current_tab = "changespecs"  # legacy tab id
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "z")

    assert handled is True
    mixin._open_models_panel.assert_called_once()


def test_open_models_panel_refreshes_indicators_when_changed() -> None:
    mixin = MagicMock()
    default_indicator = MagicMock(spec=LLMOverrideIndicator)
    alias_indicator = MagicMock(spec=AliasOverridesIndicator)
    indicators = {
        "#llm-override-indicator": default_indicator,
        "#alias-overrides-indicator": alias_indicator,
    }
    mixin.query_one.side_effect = lambda selector, _type: indicators[selector]

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=True))

    assert mixin.query_one.call_args_list == [
        call("#llm-override-indicator", LLMOverrideIndicator),
        call("#alias-overrides-indicator", AliasOverridesIndicator),
    ]
    default_indicator.refresh.assert_called_once()
    alias_indicator.refresh.assert_called_once()


def test_open_models_panel_no_refresh_when_unchanged() -> None:
    mixin = MagicMock()

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(ModelsPanelResult(changed=False))

    mixin.query_one.assert_not_called()
