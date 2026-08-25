"""Widget coverage for the Config Flags pane and restart flow."""

from __future__ import annotations

import threading
from datetime import date
from types import SimpleNamespace

import pytest
from textual.widgets import Button, Input, Static

from sase.ace.testing import AcePage, wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.feature_flags_pane import FeatureFlagsPane
from sase.ace.tui.modals.feature_flags_pane_load import FeatureFlagsPaneLoad
from sase.ace.tui.modals.feature_flags_pane_rendering import (
    ROLLOUT_FLAG_KEY,
    ROLLOUT_RECOVERY_COMMAND,
)
from sase.ace.tui.update_restart import restart_after_update_when_ready
from sase.feature_flags.cli_views import FlagView
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDiagnostic,
    FeatureFlagError,
    FlagKind,
    FlagSource,
)
from tests.ace.tui._config_center_tabs_helpers import _HostApp
from tests.feature_flags._helpers import demo_flag, flag_bead

_TODAY = date(2026, 8, 21)
_RELEASE = "0.16.0"
_STATE_PATH = "/tmp/pytest-feature-flags.json"


def _view(
    key: str,
    *,
    kind: FlagKind = "beta",
    enabled: bool = False,
    source: FlagSource = "default",
    source_detail: str = "",
    saved: bool | None = None,
    due_state: str | None = None,
    description: str | None = None,
) -> FlagView:
    definition = demo_flag(key, kind=kind, description=description)
    return FlagView(
        definition=definition,
        decision=FeatureFlagDecision(
            key=key,
            enabled=enabled,
            default=definition.default,
            source=source,
            source_detail=source_detail,
            overridden=source != "default",
        ),
        bead=flag_bead(key),
        due_state=due_state,  # type: ignore[arg-type]
        saved=saved,
    )


def _payload(
    views: tuple[FlagView, ...],
    *,
    error: str | None = None,
    diagnostics: tuple[FeatureFlagDiagnostic, ...] = (),
) -> FeatureFlagsPaneLoad:
    return FeatureFlagsPaneLoad(
        views=views,
        state_path=_STATE_PATH,
        diagnostics=diagnostics,
        today=_TODAY,
        release=_RELEASE,
        error=error,
    )


def _install_load(
    monkeypatch: pytest.MonkeyPatch,
    payload: FeatureFlagsPaneLoad,
    *,
    calls: list[int] | None = None,
) -> None:
    def load() -> FeatureFlagsPaneLoad:
        if calls is not None:
            calls.append(1)
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.modals.feature_flags_pane.load_feature_flags_pane_state",
        load,
    )


async def _open_flags_pane(
    page: AcePage,
) -> tuple[ConfigCenterModal, FeatureFlagsPane]:
    modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="flags"))
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    hub = modal.query_one("#config", ConfigHubPane)
    await page.wait_for(lambda _s: hub._active_subtab == "flags")
    await page.wait_for(lambda _s: bool(modal.query("#flags")))
    pane = modal.query_one("#flags", FeatureFlagsPane)
    await page.wait_for(lambda _s: not pane._loading)
    return modal, pane


def test_restart_helper_uses_feature_flag_purpose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restarts: list[bool] = []
    messages: list[str] = []
    app = SimpleNamespace(
        _restart_tui=lambda *, restart_axe: restarts.append(restart_axe),
        notify=lambda message, *, severity="information": messages.append(message),
        set_timer=None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.update_restart.running_background_procs",
        lambda _app: [],
    )
    restart_after_update_when_ready(
        app,
        "Feature-flag changes saved",
        deferred=False,
        restart_purpose="apply feature-flag changes",
    )
    assert restarts == [True]
    assert messages == [
        "Feature-flag changes saved — restarting ACE to apply feature-flag changes."
    ]


async def test_flags_pane_loads_rows_and_preserves_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(
        monkeypatch,
        _payload(
            (
                _view("artifact_links", enabled=True, saved=True),
                _view("cleanup_gate", enabled=False),
            )
        ),
    )
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        assert [str(view.definition.key) for view in pane._views] == [
            "artifact_links",
            "cleanup_gate",
        ]
        assert pane._current_key == "artifact_links"
        pane.action_next_flag()
        await page.pause()
        assert pane._current_key == "cleanup_gate"
        header = pane.query_one("#feature-flags-pane-header", Static).render()
        assert "2 registered" in getattr(header, "plain", str(header))


async def test_filter_focus_escape_clears_before_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(
        monkeypatch,
        _payload(
            (
                _view("artifact_links", enabled=True),
                _view("cleanup_gate", enabled=False),
            )
        ),
    )
    async with AcePage(initial_tab="agents") as page:
        modal, pane = await _open_flags_pane(page)
        pane.action_filter_flags()
        await page.wait_for(lambda _s: isinstance(page.app.focused, Input))
        filter_input = pane.query_one("#feature-flags-pane-filter", Input)
        filter_input.value = "cleanup"
        pane._apply_filter("cleanup")
        assert [str(view.definition.key) for view in pane._views] == ["cleanup_gate"]

        pane.action_escape()
        await page.pause()
        assert filter_input.display is False
        assert pane._filter_text == ""
        assert len(pane._views) == 2
        assert modal.is_mounted

        pane.action_close()
        await page.wait_for(
            lambda _s: not isinstance(page.app.screen, ConfigCenterModal)
        )


async def test_empty_and_error_states_are_not_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(monkeypatch, _payload((), error="store unreadable"))
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        description = pane.query_one(
            "#feature-flags-pane-card-description", Static
        ).render()
        plain = getattr(description, "plain", str(description))
        assert "Could not load" in plain
        assert "store unreadable" in plain


async def test_no_match_and_empty_catalog_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(monkeypatch, _payload(()))
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        empty = pane.query_one("#feature-flags-pane-card-description", Static).render()
        assert "No feature flags are registered" in getattr(empty, "plain", str(empty))

    _install_load(
        monkeypatch,
        _payload((_view("artifact_links", enabled=True),)),
    )
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        pane._apply_filter("zzz")
        missing = pane.query_one(
            "#feature-flags-pane-card-description", Static
        ).render()
        assert "No flags match" in getattr(missing, "plain", str(missing))


async def test_navigation_does_not_reread_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    _install_load(
        monkeypatch,
        _payload(
            (
                _view("artifact_links", enabled=True),
                _view("cleanup_gate", enabled=False),
            )
        ),
        calls=calls,
    )
    reads = {"saved": 0, "views": 0}

    def boom_saved() -> None:
        reads["saved"] += 1
        raise AssertionError("saved-state read during navigation")

    def boom_views(**_kwargs: object) -> tuple[FlagView, ...]:
        reads["views"] += 1
        raise AssertionError("flag_views during navigation")

    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        assert calls == [1]
        monkeypatch.setattr(
            "sase.feature_flags.state.load_saved_feature_flags", boom_saved
        )
        monkeypatch.setattr("sase.feature_flags.cli_views.flag_views", boom_views)
        pane.action_next_flag()
        await page.pause()
        pane.action_prev_flag()
        await page.pause()
        assert pane._current_key in {"artifact_links", "cleanup_gate"}
        assert calls == [1]
        assert reads == {"saved": 0, "views": 0}


async def test_toggle_confirmation_cancels_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutations: list[tuple[str, bool]] = []
    _install_load(
        monkeypatch,
        _payload((_view("artifact_links", enabled=False),)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.feature_flags_pane.set_saved_feature_flag",
        lambda key, enabled: mutations.append((key, enabled)),
    )
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await page.pause()
        confirm = page.app.screen
        assert isinstance(confirm, ConfirmActionModal)
        assert confirm._default == "cancel"
        cancel = confirm.query_one("#cancel-btn", Button)
        assert confirm.focused is cancel or page.app.focused is cancel
        await page.press("n")
        await page.wait_for(
            lambda _s: not isinstance(page.app.screen, ConfirmActionModal)
        )
        assert mutations == []
        assert pane.is_mounted


async def test_confirmed_toggle_restarts_axe_and_suppresses_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    mutations: list[tuple[str, bool]] = []
    restarts: list[bool] = []
    _install_load(
        monkeypatch,
        _payload((_view("artifact_links", enabled=False),)),
    )

    def slow_set(key: str, enabled: bool) -> None:
        mutations.append((key, enabled))
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(
        "sase.ace.tui.modals.feature_flags_pane.set_saved_feature_flag",
        slow_set,
    )
    monkeypatch.setattr(
        "sase.ace.tui.update_restart.running_background_procs",
        lambda _app: [],
    )
    async with AcePage(initial_tab="agents") as page:
        page.app._restart_tui = (  # type: ignore[method-assign]
            lambda *, restart_axe: restarts.append(restart_axe)
        )
        _modal, pane = await _open_flags_pane(page)
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: started.is_set())
        assert pane._mutating is True
        pane.action_toggle_flag()
        await page.pause()
        assert not isinstance(page.app.screen, ConfirmActionModal)
        release.set()
        await page.wait_for(lambda _s: restarts == [True])
        assert mutations == [("artifact_links", True)]


async def test_mutation_failure_stays_in_pane_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restarts: list[bool] = []
    notices: list[str] = []
    _install_load(
        monkeypatch,
        _payload((_view("artifact_links", enabled=False),)),
    )

    def fail(_key: str, _enabled: bool) -> None:
        raise FeatureFlagError("store corrupt")

    monkeypatch.setattr(
        "sase.ace.tui.modals.feature_flags_pane.set_saved_feature_flag",
        fail,
    )
    async with AcePage(initial_tab="agents") as page:
        page.app._restart_tui = (  # type: ignore[method-assign]
            lambda *, restart_axe: restarts.append(restart_axe)
        )
        original_notify = page.app.notify

        def capture(message: str, **kwargs: object) -> None:
            notices.append(message)
            original_notify(message, **kwargs)  # type: ignore[arg-type]

        page.app.notify = capture  # type: ignore[method-assign]
        _modal, pane = await _open_flags_pane(page)
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: any("store corrupt" in item for item in notices))
        assert restarts == []
        assert pane.is_mounted
        assert pane._mutating is False


async def test_self_disable_confirmation_includes_recovery_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(
        monkeypatch,
        _payload(
            (
                _view(
                    ROLLOUT_FLAG_KEY,
                    kind="sunset",
                    enabled=True,
                    description="The Config catalog exposes the Flags pane.",
                ),
            )
        ),
    )
    async with AcePage(initial_tab="agents") as page:
        _modal, pane = await _open_flags_pane(page)
        pane.action_toggle_flag()
        await page.expect_modal("ConfirmActionModal")
        modal = page.app.screen
        assert isinstance(modal, ConfirmActionModal)
        assert ROLLOUT_RECOVERY_COMMAND in (modal._subject or "")
        assert "Flags pane will disappear" in (modal._subject or "")
        await page.press("n")


def test_active_proc_queues_restart_then_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restarts: list[bool] = []
    messages: list[str] = []
    timers: list[object] = []
    app = SimpleNamespace(
        _restart_tui=lambda *, restart_axe: restarts.append(restart_axe),
        notify=lambda message, *, severity="information": messages.append(message),
        set_timer=lambda _interval, callback: timers.append(callback),
    )
    monkeypatch.setattr(
        "sase.ace.tui.update_restart.running_background_procs",
        lambda _app: [SimpleNamespace(label="build")],
    )
    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 0.0)
    restart_after_update_when_ready(
        app,
        "Feature-flag changes saved",
        deferred=False,
        deadline=10.0,
        restart_purpose="apply feature-flag changes",
    )
    assert any("restart queued" in message for message in messages)
    assert restarts == []
    assert timers

    monkeypatch.setattr("sase.ace.tui.update_restart.time.monotonic", lambda: 100.0)
    timers[-1]()
    assert restarts == [True]
    assert any("restart wait expired" in message for message in messages)
    assert any("apply feature-flag changes" in message for message in messages)


async def test_flags_pane_forwards_config_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_load(
        monkeypatch,
        _payload((_view("artifact_links", enabled=True),)),
    )
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(config_entry=ConfigHubEntry(subtab="flags"))
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: hub._active_subtab == "flags")
        pane = modal.query_one("#flags", FeatureFlagsPane)
        await wait_for(pilot, lambda: not pane._loading)

        def create(_self: ConfigHubPane, subtab: str) -> Static:
            return Static(subtab, id=subtab)

        monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
        await pilot.press("0", "6")
        await wait_for(pilot, lambda: hub._active_subtab == "xprompts")
        assert hub._pending_subtab_select is False
