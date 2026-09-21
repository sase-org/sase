"""Tests for opening the Models panel from leader mode."""

from typing import cast
from unittest.mock import MagicMock, call

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.widgets import (
    AliasOverridesIndicator,
    ProviderDisablesIndicator,
    ProviderUsageIndicator,
)
from sase.ace.tui.widgets.launch_context_source import LaunchContextSource
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


def test_leader_handler_repeats_models_panel_route() -> None:
    mixin = MagicMock()
    mixin._keymap_registry = full_registry()
    mixin.current_tab = "agents"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    assert LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "m") is True
    mixin._leader_mode_active = True
    assert (
        LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "comma")
        is True
    )

    assert mixin._open_models_panel.call_count == 2
    assert mixin._last_leader_key == "m"


def _launch_indicators_mixin() -> tuple[MagicMock, MagicMock, dict[str, MagicMock]]:
    """Build a mixin whose queries resolve the pills plus the context source."""
    mixin = MagicMock()
    source = MagicMock(spec=LaunchContextSource)
    indicators = {
        "#alias-overrides-indicator": MagicMock(spec=AliasOverridesIndicator),
        "#provider-disables-indicator": MagicMock(spec=ProviderDisablesIndicator),
        "#provider-usage-indicator": MagicMock(spec=ProviderUsageIndicator),
        "#launch-context-source": source,
    }
    mixin.query_one.side_effect = lambda selector, _type: indicators[selector]
    return mixin, source, indicators


def test_refresh_launch_indicators_refreshes_all_indicators() -> None:
    mixin, source, indicators = _launch_indicators_mixin()

    LeaderModeMixin._refresh_launch_indicators(cast(LeaderModeMixin, mixin))

    assert mixin.query_one.call_args_list == [
        call("#alias-overrides-indicator", AliasOverridesIndicator),
        call("#provider-disables-indicator", ProviderDisablesIndicator),
        call("#provider-usage-indicator", ProviderUsageIndicator),
        call("#launch-context-source", LaunchContextSource),
    ]
    source.invalidate_launch_default.assert_called_once()
    for selector in (
        "#alias-overrides-indicator",
        "#provider-disables-indicator",
        "#provider-usage-indicator",
    ):
        indicators[selector].refresh.assert_called_once_with()


def test_refresh_launch_indicators_invalidates_cached_default_without_routing_flag() -> (
    None
):
    mixin, source, _indicators = _launch_indicators_mixin()

    LeaderModeMixin._refresh_launch_indicators(cast(LeaderModeMixin, mixin))

    source.invalidate_launch_default.assert_called_once()


def test_open_models_panel_routes_to_config_launch() -> None:
    mixin = MagicMock()

    LeaderModeMixin._open_models_panel(cast(LeaderModeMixin, mixin))

    mixin.push_screen.assert_not_called()
    mixin._open_config_center.assert_called_once()
    args, kwargs = mixin._open_config_center.call_args
    assert args == ("config",)
    entry = kwargs["config_entry"]
    assert isinstance(entry, ConfigHubEntry)
    assert entry.subtab == "launch"


def test_open_models_panel_invalidates_default_on_provider_routing_change() -> None:
    mixin, source, indicators = _launch_indicators_mixin()

    LeaderModeMixin._refresh_launch_indicators(
        cast(LeaderModeMixin, mixin),
        provider_routing_changed=True,
    )

    source.invalidate_launch_default.assert_called_once()
    for selector in (
        "#alias-overrides-indicator",
        "#provider-disables-indicator",
        "#provider-usage-indicator",
    ):
        indicators[selector].refresh.assert_called_once_with()
