"""Wire `,U` to the Update panel and the scoped preview proc."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.update_run import UpdateRunActionsMixin
from sase.ace.tui.actions.update_toast import UpdateToastMixin
from sase.ace.tui.actions import update_toast
from sase.ace.tui.modals.plugins_browser_comprehensive_update_execution import (
    scoped_preview_cl_name,
)
from sase.ace.tui.modals.update_panel import UpdatePanel, UpdatePanelResult
from sase.ace.tui.update_panel_state import build_update_panel_state
from sase.ace.update_scope import UpdateScope
from sase.updates import UpdateStatus
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)

_NOW = 1_000.0


class _ShortcutHarness(UpdateRunActionsMixin, BaseActionsMixin):
    def __init__(self) -> None:
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.submitted: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.preview_requests: list[Any] = []
        self._automatic_update_status = None
        self._automatic_update_provider_names: tuple[str, ...] | None = ("claude",)

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _submit_update_preview_proc(self, request: Any) -> bool:
        self.preview_requests.append(request)
        return super()._submit_update_preview_proc(request)

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object:
        assert_session_worker_submit_signature(args, kwargs)
        self.submitted = (args, kwargs)
        return object()


class _PanelHarness(UpdateRunActionsMixin):
    def __init__(self) -> None:
        self.screen: object | None = None
        self.update_checks: list[dict[str, bool]] = []
        self._automatic_update_status = None
        self._automatic_update_check_in_flight = False

    def _schedule_automatic_update_check(
        self, *, periodic: bool, force: bool = False
    ) -> None:
        self.update_checks.append({"periodic": periodic, "force": force})
        self._automatic_update_check_in_flight = True


class _ToastPanelHarness(UpdateRunActionsMixin, UpdateToastMixin):
    def __init__(self) -> None:
        self.screen: object | None = None
        self._automatic_update_check_in_flight = True
        self._automatic_update_status = None
        self._automatic_update_provider_names = None
        self._update_toast_shown = True

    def query_one(self, *_args: object) -> object:
        raise AssertionError("indicator must not be required to refresh the panel")


def test_chosen_scope_submits_update_preview_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _ShortcutHarness()
    harness.action_update_sase_shortcut()
    callback = harness.pushed_callbacks[0]
    assert callback is not None

    callback(UpdatePanelResult(scope="providers"))

    assert harness.submitted is not None
    args, kwargs = harness.submitted
    assert args[0] == "update-preview"
    assert kwargs["display_name"] == "plan update"
    assert kwargs["cl_name"] == scoped_preview_cl_name(UpdateScope.PROVIDERS)
    assert kwargs["dedup_key"] == "update-preview"
    assert kwargs["exclusive_scopes"] == ()
    assert len(harness.preview_requests) == 1
    request = harness.preview_requests[0]
    assert request.provider_names == ("claude",)
    assert request.scope is UpdateScope.PROVIDERS
    assert request.auto_approve is False


def test_auto_approve_result_copies_explicit_flag_into_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _ShortcutHarness()
    harness.action_update_sase_shortcut()
    callback = harness.pushed_callbacks[0]
    assert callback is not None

    callback(UpdatePanelResult(scope="sase", auto_approve=True))

    assert len(harness.preview_requests) == 1
    request = harness.preview_requests[0]
    assert request.provider_names == ("claude",)
    assert request.scope is UpdateScope.SASE
    assert request.auto_approve is True


def test_canceling_the_panel_does_not_submit_a_preview_proc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _ShortcutHarness()
    harness.action_update_sase_shortcut()
    callback = harness.pushed_callbacks[0]
    assert callback is not None

    callback(None)

    assert harness.submitted is None


def test_recheck_marks_panel_busy_and_schedules_existing_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _PanelHarness()
    harness.screen = UpdatePanel(build_update_panel_state(None, now=_NOW))

    harness.on_update_panel_recheck_requested(UpdatePanel.RecheckRequested())

    assert isinstance(harness.screen, UpdatePanel)
    assert harness.screen._state.rechecking is True
    assert harness.update_checks == [{"periodic": True, "force": True}]


def test_refresh_noops_when_the_panel_is_not_the_active_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _PanelHarness()
    harness.screen = object()

    harness._refresh_open_update_panel(rechecking=True)

    assert not isinstance(harness.screen, UpdatePanel)


def test_applied_update_status_refreshes_the_open_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _ToastPanelHarness()
    harness.screen = UpdatePanel(build_update_panel_state(None, now=_NOW))
    status = UpdateStatus(checked_at=_NOW, components=())

    harness._apply_startup_update_status(
        status,
        update_toast._UpdateToastConfig(startup_toast=False, indicator=False),
    )

    assert isinstance(harness.screen, UpdatePanel)
    assert harness.screen._state == build_update_panel_state(
        status,
        now=_NOW,
        rechecking=True,
    )


def test_failed_automatic_check_still_clears_rechecking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.time", lambda: _NOW)
    harness = _ToastPanelHarness()
    harness.screen = UpdatePanel(
        build_update_panel_state(None, now=_NOW, rechecking=True)
    )

    harness._complete_automatic_update_check(None)

    assert isinstance(harness.screen, UpdatePanel)
    assert harness.screen._state.rechecking is False
    assert harness._automatic_update_check_in_flight is False


def test_shortcut_dispatch_does_not_call_cached_status_accessors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("chord dispatch must not read cached update accessors")

    monkeypatch.setattr("time.time", lambda: _NOW)
    monkeypatch.setattr("sase.updates.get_cached_update_status", fail)
    monkeypatch.setattr("sase.updates.cache.get_cached_update_status", fail)
    monkeypatch.setattr("sase.agents_sync.get_agents_sync_status", fail)
    monkeypatch.setattr("sase.agents_sync.status.get_agents_sync_status", fail)
    harness = _ShortcutHarness()

    harness.action_update_sase_shortcut()

    assert isinstance(harness.pushed_modals[0], UpdatePanel)
    assert harness.pushed_modals[0]._state == build_update_panel_state(None, now=_NOW)
