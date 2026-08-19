"""Tests for the Admin Center Logs-tab cutover."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.commands import build_command_catalog
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.keymaps.types import LeaderModeKeymaps
from sase.ace.tui.modals.config_center_modal import (
    _TAB_LABELS,
    _TAB_ORDER,
    CenterTab,
    ConfigCenterModal,
)
from sase.ace.tui.widgets import KeybindingFooter
from sase.logs import clear_registered_errors, register_error
from tests.ace.tui._leader_keymap_helpers import (
    _capture_bindings,
    _last_labels,
)


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


class _ActionApp(BaseActionsMixin):
    def __init__(self) -> None:
        self.pushed_modals: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._last_admin_center_tab: CenterTab | None = None
        self._keymap_registry = load_keymap_registry({})
        self.revalidation_count = 0

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _schedule_updates_indicator_revalidation(self) -> None:
        self.revalidation_count += 1


def test_leader_mode_drops_log_panel_key() -> None:
    registry = load_keymap_registry({})

    assert "log_panel" not in registry.leader_mode.keys
    assert "log_panel" not in LeaderModeKeymaps().keys


def test_stale_log_panel_override_is_filtered_out() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"log_panel": "L"}}}}}
    )

    assert "log_panel" not in registry.leader_mode.keys


def test_stale_task_queue_override_is_filtered_out() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"task_queue": "t"}}}}}
    )

    assert "task_queue" not in registry.leader_mode.keys


def test_admin_center_tabs_are_alphabetical_by_label() -> None:
    assert _TAB_ORDER == (
        "config",
        "logs",
        "procs",
        "projects",
        "statistics",
        "updates",
        "xprompts",
    )

    labels = dict(_TAB_LABELS)
    assert list(_TAB_ORDER) == sorted(
        _TAB_ORDER,
        key=lambda tab: labels[tab].casefold(),
    )


def test_keyless_logs_command_opens_logs_tab() -> None:
    catalog = build_command_catalog(load_keymap_registry({}))
    assert not any(c.id == "leader.log_panel" for c in catalog)
    spec = next(c for c in catalog if c.id == "logs")

    assert spec.label == "Open logs panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_log_panel"
    assert "launch failures" in spec.aliases


def test_keyless_tasks_command_opens_tasks_tab() -> None:
    catalog = build_command_catalog(load_keymap_registry({}))
    assert not any(c.id == "leader.task_queue" for c in catalog)
    spec = next(c for c in catalog if c.id == "tasks")

    assert spec.label == "Open procs panel"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_tasks_panel"
    assert "proc queue" in spec.aliases


def test_keyless_statistics_command_opens_statistics_tab() -> None:
    catalog = build_command_catalog(load_keymap_registry({}))
    spec = next(c for c in catalog if c.id == "statistics")

    assert spec.label == "Open statistics"
    assert spec.key_display == ""
    assert spec.key_sequence == ()
    assert spec.tabs == ("artifacts", "agents", "axe")
    assert spec.executor.kind == "app_action"
    assert spec.executor.action == "open_statistics_panel"
    assert "metrics" in spec.aliases
    assert "telemetry" in spec.aliases


def test_open_log_panel_action_pushes_admin_center_on_logs() -> None:
    app = _ActionApp()

    app.action_open_log_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "logs"


def test_jump_to_last_error_action_pushes_admin_center_on_logs() -> None:
    app = _ActionApp()

    app.action_jump_to_last_error()

    assert app.notifications == [("No error registered in this ACE session", None)]
    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "logs"
    assert modal._log_error_target is None


def test_jump_to_last_error_passes_registered_error_target() -> None:
    app = _ActionApp()
    registered = register_error(
        error_id="err_260617_143000_7f3a9c",
        source_id="launch_failures",
        summary="Launch failed",
    )

    app.action_jump_to_last_error()

    assert app.notifications == []
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "logs"
    assert modal._log_error_target is registered


def test_open_tasks_panel_action_pushes_admin_center_on_tasks() -> None:
    app = _ActionApp()

    app.action_open_tasks_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "procs"


def test_open_statistics_panel_action_pushes_admin_center_on_statistics() -> None:
    app = _ActionApp()

    app.action_open_statistics_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "statistics"


def test_open_updates_panel_action_pushes_admin_center_on_updates() -> None:
    app = _ActionApp()

    app.action_open_updates_panel()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "updates"
    assert modal._auto_update is False


def test_update_sase_shortcut_opens_updates_with_auto_update() -> None:
    app = _ActionApp()

    app.action_update_sase_shortcut()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab == "updates"
    assert modal._auto_update is True
    assert modal._comprehensive_provider_names is None


def test_update_shortcut_immutably_captures_provider_projection() -> None:
    app = _ActionApp()
    app._automatic_update_provider_names = ("claude", "codex")

    app.action_update_sase_shortcut()
    app._automatic_update_provider_names = ("gemini",)

    modal = app.pushed_modals[0]
    assert modal._comprehensive_provider_names == ("claude", "codex")


def test_update_shortcut_dispatch_performs_no_disk_or_subprocess_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("keypress dispatch must stay in-memory")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)
    app = _ActionApp()
    app._automatic_update_provider_names = ("claude",)

    app.action_update_sase_shortcut()

    assert len(app.pushed_modals) == 1
    assert app.pushed_modals[0]._comprehensive_provider_names == ("claude",)


def test_open_config_center_action_requests_home() -> None:
    app = _ActionApp()

    app.action_open_config_center()

    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, ConfigCenterModal)
    assert modal._initial_tab is None
    assert modal._active_tab is None
    assert modal._resume_tab is None
    assert modal._opener_binding == "number_sign"


def test_dismissal_validates_history_and_revalidates_updates() -> None:
    app = _ActionApp()
    app._last_admin_center_tab = "logs"

    app._on_config_center_dismissed(None)
    app._on_config_center_dismissed("not-a-tab")
    assert app._last_admin_center_tab == "logs"

    app._on_config_center_dismissed("procs")
    assert app._last_admin_center_tab == "procs"
    assert app.revalidation_count == 3


def test_footer_omits_log_panel_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("patches", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "log panel" not in _last_labels(captured)


def test_footer_omits_task_queue_on_all_tabs() -> None:
    footer = KeybindingFooter()
    captured = _capture_bindings(footer)

    for tab in ("patches", "agents", "axe"):
        footer.update_leader_bindings(current_tab=tab)
        assert "task queue" not in _last_labels(captured)
