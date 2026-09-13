"""Both-states coverage for Refresh panel gesture wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.event_refresh._freshness import freshness_label
from sase.ace.tui.actions.refresh_panel import (
    FULL_HISTORY_MIGRATION_BANNER,
    REFRESH_PANEL_COMMAND_LABEL,
    REFRESH_TAB_COMMAND_LABEL,
)
from sase.ace.tui.commands import iter_app_commands, iter_mode_commands
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings
from sase.ace.tui.modals.help_modal.axe_bindings import axe_bindings
from sase.ace.tui.modals.help_modal.patches_bindings import cls_bindings
from sase.ace.tui.modals.refresh_panel_modal import RefreshPanelModal
from sase.ace.tui.widgets import KeybindingFooter
from sase.feature_flags import override_flags
from sase.llm_provider.usage.refresh import (
    USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
    UsageRefreshReceipt,
    _UsageRefreshProviderResult,
)
from tests.ace.tui._leader_keymap_helpers import (
    _FakeApp,
    _capture_bindings,
    _last_labels,
)


class _DispatchApp(BaseActionsMixin):
    """Minimal host for refresh-panel dispatch."""

    def __init__(
        self,
        *,
        current_tab: str = "agents",
        artifacts_subtab: str = "patches",
        pane_key: str = "patches",
    ) -> None:
        self.current_tab = current_tab  # type: ignore[assignment]
        self.current_artifacts_subtab = artifacts_subtab
        self.current_artifacts_pane_key = pane_key
        self.refresh_interval = 10
        self._countdown_remaining = 4
        self._last_full_sanity_refresh = 99.0
        self._agents_history_reconcile_pending = True
        self.pushed: list[tuple[Any, Any]] = []
        self.notifications: list[str] = []
        self.scheduled_agents: list[dict[str, Any]] = []
        self.other_calls: list[str] = []
        self.worker_calls: list[dict[str, Any]] = []
        self.auto_refresh_calls = 0
        self.auto_refresh_sanity_at_call: float | None = None

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed.append((screen, callback))

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)

    def run_worker(self, fn: Any, *, thread: bool = False, **kwargs: Any) -> Any:
        self.worker_calls.append(
            {"fn": fn, "thread": thread, "exit_on_error": kwargs.get("exit_on_error")}
        )
        return object()

    def call_from_thread(self, callback: Any, *args: Any) -> None:
        callback(*args)

    def _schedule_agents_async_refresh(self, **kwargs: Any) -> None:
        self.scheduled_agents.append(kwargs)

    def _schedule_agents_fleet_refresh(self, **_: Any) -> None:
        self.other_calls.append("fleet")

    def _schedule_patches_async_refresh(self) -> None:
        self.other_calls.append("patches")

    def _request_active_artifacts_refresh(self) -> None:
        self.other_calls.append("artifacts")

    def _schedule_targeted_axe_refresh(self) -> None:
        self.other_calls.append("targeted_axe")

    def _schedule_axe_async_refresh(self) -> None:
        self.other_calls.append("axe")

    def _on_auto_refresh(self) -> None:
        self.auto_refresh_sanity_at_call = self._last_full_sanity_refresh
        self.auto_refresh_calls += 1


def _help_labels(bindings_fn: Any) -> set[str]:
    registry = load_keymap_registry({})
    return {label for _section, rows in bindings_fn(registry) for _key, label in rows}


def _started_receipt(*providers: str) -> UsageRefreshReceipt:
    results = tuple(
        _UsageRefreshProviderResult(
            provider=name,
            status="reserved",
            reason=None,
            operation_id=f"op-{name}",
        )
        for name in providers
    )
    return UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin="ace",
        operation_ids=tuple(item.operation_id or "" for item in results),
        providers=results,
    )


def test_flag_on_refresh_pushes_panel_and_this_tab_dispatches() -> None:
    app = _DispatchApp()

    with override_flags(refresh_panel=True):
        app.action_refresh()

    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert isinstance(modal, RefreshPanelModal)
    assert modal.tab_label == "Agents"
    assert modal._banner is None
    assert modal._rows[modal._cursor].choice == "this_tab"
    assert app.scheduled_agents == []

    callback("this_tab")

    assert app.scheduled_agents == [{"source": "manual", "full_history": False}]
    assert "fleet" in app.other_calls
    assert app.notifications == ["Refreshed"]


def test_flag_on_full_history_works_from_artifacts_and_axe() -> None:
    for tab in ("artifacts", "axe"):
        app = _DispatchApp(current_tab=tab)
        with override_flags(refresh_panel=True):
            app._dispatch_refresh_choice("full_history")

        assert app.scheduled_agents == [
            {
                "source": "manual_full_history",
                "full_history": True,
                "full_history_reason": "manual_full_history_refresh",
            }
        ]
        assert app.notifications == ["Refreshing Agents from full history"]
        assert app._agents_history_reconcile_pending is False


def test_flag_on_usage_runs_off_the_ui_thread() -> None:
    app = _DispatchApp()
    receipt = _started_receipt("synth")

    with (
        override_flags(refresh_panel=True),
        patch(
            "sase.ace.tui.actions.refresh_panel.submit_usage_refresh",
            return_value=receipt,
        ) as submit,
    ):
        app._dispatch_refresh_choice("usage")
        submit.assert_not_called()
        assert len(app.worker_calls) == 1
        assert app.worker_calls[0]["thread"] is True
        app.worker_calls[0]["fn"]()

    submit.assert_called_once_with(None, explicit=True, origin="ace")
    assert app.notifications == ["Refreshing usage: synth"]


def test_flag_on_everything_zeroes_sanity_before_sweep() -> None:
    app = _DispatchApp()

    with (
        override_flags(refresh_panel=True),
        patch(
            "sase.ace.tui.actions.refresh_panel.submit_usage_refresh",
            return_value=_started_receipt("synth"),
        ),
    ):
        app._dispatch_refresh_choice("everything")

    assert app.auto_refresh_calls == 1
    assert app.auto_refresh_sanity_at_call == 0.0
    assert app.scheduled_agents[-1]["full_history"] is True
    assert app.worker_calls
    assert app.worker_calls[0]["thread"] is True
    assert "Refreshing everything" in app.notifications


def test_flag_on_comma_y_opens_panel_on_full_history() -> None:
    app = _FakeApp(current_tab="agents")

    with override_flags(refresh_panel=True):
        handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 0
    assert app.refresh_count == 1
    assert app.refresh_panel_opens == [
        {
            "initial_choice": "full_history",
            "banner": FULL_HISTORY_MIGRATION_BANNER,
        }
    ]


def test_flag_on_comma_y_opens_panel_from_non_agents_tab() -> None:
    app = _FakeApp(current_tab="patches")

    with override_flags(refresh_panel=True):
        handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 0
    assert app.refresh_panel_opens[0]["initial_choice"] == "full_history"


def test_flag_on_footer_palette_and_help_omit_comma_y() -> None:
    with override_flags(refresh_panel=True):
        footer = KeybindingFooter()
        captured = _capture_bindings(footer)
        footer.update_leader_bindings(current_tab="agents")
        assert "full history refresh" not in _last_labels(captured)

        catalog_ids = {spec.id for spec in iter_mode_commands(load_keymap_registry({}))}
        assert "leader.full_history_refresh" not in catalog_ids
        refresh = next(
            spec
            for spec in iter_app_commands(load_keymap_registry({}))
            if spec.id == "app.refresh"
        )
        assert refresh.label == REFRESH_PANEL_COMMAND_LABEL

        labels = _help_labels(agents_bindings)
        assert "Refresh from full history" not in labels
        assert "Open Refresh panel" in labels
        assert "Open Refresh panel" in _help_labels(cls_bindings)
        assert "Open Refresh panel" in _help_labels(axe_bindings)


def test_flag_off_refresh_is_immediate() -> None:
    app = _DispatchApp()

    with override_flags(refresh_panel=False):
        app.action_refresh()

    assert app.pushed == []
    assert app.scheduled_agents == [{"source": "manual", "full_history": False}]
    assert app.notifications == ["Refreshed"]


def test_flag_off_comma_y_calls_full_history_directly() -> None:
    app = _FakeApp(current_tab="agents")

    with override_flags(refresh_panel=False):
        handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 1
    assert app.refresh_panel_opens == []


def test_flag_off_footer_palette_and_help_keep_comma_y() -> None:
    with override_flags(refresh_panel=False):
        footer = KeybindingFooter()
        captured = _capture_bindings(footer)
        footer.update_leader_bindings(current_tab="agents")
        assert "full history refresh" in _last_labels(captured)

        catalog_ids = {spec.id for spec in iter_mode_commands(load_keymap_registry({}))}
        assert "leader.full_history_refresh" in catalog_ids
        refresh = next(
            spec
            for spec in iter_app_commands(load_keymap_registry({}))
            if spec.id == "app.refresh"
        )
        assert refresh.label == REFRESH_TAB_COMMAND_LABEL

        labels = _help_labels(agents_bindings)
        assert "Refresh from full history" in labels
        assert "Open Refresh panel" not in labels
        assert "Open Refresh panel" not in _help_labels(cls_bindings)
        assert "Open Refresh panel" not in _help_labels(axe_bindings)


def test_panel_rows_use_in_memory_freshness_and_tab_label() -> None:
    app = _DispatchApp(
        current_tab="artifacts",
        artifacts_subtab="beads",
        pane_key="beads",
    )
    app._surface_refreshed_mono = {"artifacts": 0.0, "agents_full_history": 0.0}

    with (
        override_flags(refresh_panel=True),
        patch(
            "sase.ace.tui.actions.refresh_panel.surface_refreshed_age",
            side_effect=lambda _app, surface: {
                "artifacts": 12.0,
                "agents_full_history": 7200.0,
            }.get(surface),
        ),
    ):
        rows = {row.choice: row for row in app._refresh_panel_rows()}

    assert app._refresh_tab_label() == "Artifacts › Beads"
    assert rows["this_tab"].target == "Artifacts › Beads"
    assert rows["this_tab"].chip == freshness_label(12.0)
    assert rows["full_history"].target == "Agents"
    assert rows["full_history"].chip == freshness_label(7200.0)
    assert rows["everything"].chip == "heavier"
    assert app._auto_refresh_label() == "auto-refresh every 10s · next in 4s"


def test_provider_pane_label_does_not_dispatch_on_ref_prefix() -> None:
    app = _DispatchApp(
        current_tab="artifacts",
        artifacts_subtab="ref:plan",
        pane_key="ref:plan",
    )

    assert app._refresh_tab_label() == "Artifacts › Plan"


def test_flag_on_cancel_does_not_refresh() -> None:
    app = _DispatchApp()

    with override_flags(refresh_panel=True):
        app.action_refresh()
        _modal, callback = app.pushed[0]
        callback(None)

    assert app.scheduled_agents == []
    assert app.notifications == []


@pytest.mark.parametrize(
    ("reason", "started", "expected"),
    [
        ("config_disabled", False, "subscription usage collection is disabled"),
        (None, False, "Usage refresh already running"),
    ],
)
def test_usage_receipt_toasts(
    reason: str | None,
    started: bool,
    expected: str,
) -> None:
    app = _DispatchApp()
    receipt = UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin="ace",
        operation_ids=("op-1",) if started else (),
        providers=(
            _UsageRefreshProviderResult(
                provider="synth",
                status="disabled" if reason else "joined",
                reason=reason,
                operation_id="op-1" if started else None,
            ),
        ),
    )

    app._notify_usage_refresh_receipt(receipt)

    assert app.notifications == [expected]
