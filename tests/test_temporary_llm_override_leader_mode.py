"""Leader-mode dispatch behavior for temporary LLM overrides."""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.modals.temporary_llm_override_modal import TemporaryOverrideResult
from sase.ace.tui.widgets import LLMOverrideIndicator

from tests._temporary_llm_override_helpers import full_registry


def test_leader_handler_dispatches_temporary_llm_override() -> None:
    """The configured leader chord opens the temporary override modal."""
    mixin = MagicMock()
    mixin._keymap_registry = full_registry()
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "m")

    assert handled is True
    mixin._open_temporary_llm_override_modal.assert_called_once()


def test_temporary_override_dismiss_set_refreshes_top_bar_indicator() -> None:
    """A successful set result refreshes the persistent top-bar badge."""
    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_temporary_llm_override_modal(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(TemporaryOverrideResult(action="set"))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()
    mixin.notify.assert_not_called()


def test_temporary_override_dismiss_clear_refreshes_top_bar_indicator() -> None:
    """A clear result refreshes the badge and keeps the clear toast."""
    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_temporary_llm_override_modal(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(TemporaryOverrideResult(action="cleared", role="primary"))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()
    mixin.notify.assert_called_once_with("Cleared primary model override")


def test_temporary_override_dismiss_worker_clear_toast() -> None:
    """The leader callback names worker clears distinctly."""
    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_temporary_llm_override_modal(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(TemporaryOverrideResult(action="cleared", role="worker"))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()
    mixin.notify.assert_called_once_with("Cleared worker model override")
