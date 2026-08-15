"""Models-panel provider-routing modal and title tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from textual.widgets import OptionList, Static
from textual.worker import WorkerState

import sase.ace.tui.modals.models_panel as models_panel_module
import sase.ace.tui.modals.models_panel_providers as providers
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    DurationPickerModal,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_providers import (
    _ProviderRoutingModal,
    _ProviderRoutingSnapshot,
    _load_provider_routing_snapshot,
    _provider_description_text,
    _render_provider_row,
)
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)
from sase.llm_provider import ProviderRoutingStatus
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
    wait_for,
)


def _disable(
    provider: str,
    *,
    expires_at: float | None = None,
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source="test",
    )


def _status(
    provider: str,
    *,
    model_count: int = 2,
    cli_available: bool = True,
    active_disable: TemporaryProviderDisable | None = None,
    hidden: bool = False,
    affected_aliases: tuple[str, ...] = ("default",),
) -> ProviderRoutingStatus:
    return ProviderRoutingStatus(
        provider=provider,
        model_count=model_count,
        cli_available=cli_available,
        active_disable=active_disable,
        hidden_from_model_pickers=hidden,
        affected_aliases=affected_aliases,
    )


def _snapshot(
    *statuses: ProviderRoutingStatus,
    disables: dict[str, TemporaryProviderDisable] | None = None,
    alias_views=None,
) -> _ProviderRoutingSnapshot:
    return _ProviderRoutingSnapshot(
        statuses=tuple(statuses),
        provider_disables=disables or {},
        alias_views=tuple(alias_views or (make_alias_view("default", "default"),)),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=100.0,
    )


def _until_result() -> ResolvedOverrideUntil:
    return ResolvedOverrideUntil(
        target=datetime.fromtimestamp(5_000.0, UTC),
        expires_at=5_000.0,
        target_display="Ends Thu Jan 1 at 1:23 AM UTC",
        notification_display="Thu Jan 1, 1:23 AM UTC",
        remaining_display="1h",
        timezone_display="UTC",
    )


def test_render_provider_rows_show_all_states() -> None:
    available = _render_provider_row(
        _status("codex", model_count=3),
        colors={"codex": "#10A37F"},
        now=100.0,
    )
    missing = _render_provider_row(
        _status("grok", model_count=1, cli_available=False),
        colors={},
        now=100.0,
    )
    disabled = _render_provider_row(
        _status("claude", active_disable=_disable("claude", expires_at=3_820.0)),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert available.plain == "CODEX          3 models     available"
    assert missing.plain == "GROK           1 model      CLI missing"
    assert disabled.plain == "CLAUDE         2 models     disabled · 1h2m left"


def test_provider_description_lists_disabled_effect_and_aliases() -> None:
    description = _provider_description_text(
        _status(
            "claude",
            active_disable=_disable("claude", expires_at=None),
            affected_aliases=("large", "medium", "xlarge"),
        ),
        now=100.0,
    )

    assert "New launches and fallbacks route around CLAUDE" in description.plain
    assert "running provider processes continue" in description.plain
    assert "Affected aliases: @large, @medium, @xlarge." in description.plain


def test_panel_sync_row_build_uses_captured_rows_without_provider_read(
    monkeypatch,
) -> None:
    disable = _disable("codex", expires_at=None)
    panel = ModelsPanel()
    panel._provider_disables = {"codex": disable}
    panel._views = [make_alias_view("default", "default")]
    provider_read = MagicMock(side_effect=AssertionError("synchronous provider read"))
    monkeypatch.setattr(providers, "get_active_provider_disables", provider_read)
    build_alias_views = MagicMock(side_effect=AssertionError("synchronous alias read"))
    monkeypatch.setattr(models_panel_module, "build_alias_views", build_alias_views)

    panel._build_options()

    provider_read.assert_not_called()
    build_alias_views.assert_not_called()


def test_provider_snapshot_worker_path_reads_authoritative_state(monkeypatch) -> None:
    disable = _disable("codex", expires_at=None)
    provider_read = MagicMock(return_value={"codex": disable})
    status_mock = MagicMock(return_value=(_status("codex", active_disable=disable),))
    view_mock = MagicMock(return_value=[make_alias_view("default", "default")])
    color_mock = MagicMock(return_value={"codex": "#10A37F"})
    monkeypatch.setattr(providers, "get_active_provider_disables", provider_read)
    monkeypatch.setattr(providers, "build_provider_routing_statuses", status_mock)
    monkeypatch.setattr(providers, "build_alias_views", view_mock)
    monkeypatch.setattr(providers, "provider_cli_status_color_map", color_mock)

    snapshot = _load_provider_routing_snapshot(100.0)

    provider_read.assert_called_once_with(100.0)
    status_mock.assert_called_once_with({"codex": disable})
    view_mock.assert_called_once_with(now=100.0, provider_disables={"codex": disable})
    color_mock.assert_called_once_with()
    assert snapshot.provider_disables == {"codex": disable}


async def test_panel_p_opens_provider_routing_modal(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    snapshot = _snapshot(_status("claude"), _status("codex"))
    monkeypatch.setattr(
        providers,
        "_load_provider_routing_snapshot",
        lambda _now=None: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _ProviderRoutingModal)


async def test_provider_modal_initial_snapshot_does_not_emit_change() -> None:
    before = _snapshot(_status("claude"))
    after = _snapshot(_status("claude"), disables={})
    on_snapshot = MagicMock()

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._snapshot is after)

    assert modal._changed is False
    on_snapshot.assert_not_called()


async def test_panel_initial_provider_snapshot_does_not_mark_routing_changed(
    monkeypatch,
) -> None:
    views = [make_alias_view("default", "default")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("codex", expires_at=None)
    snapshot = _snapshot(
        _status("codex", active_disable=disable),
        disables={"codex": disable},
        alias_views=views,
    )
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: panel._provider_snapshot is snapshot)

    assert panel._changed is False
    assert panel._provider_routing_changed is False
    assert panel._provider_disables == {"codex": disable}


async def test_provider_modal_omits_hidden_provider_and_opens_duration() -> None:
    snapshot = _snapshot(
        _status("claude"),
        _status("fakey", hidden=True),
        _status("codex", cli_available=False),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-routing-list", OptionList)
        ids = [str(option.id) for option in option_list.options]
        assert ids == ["claude", "codex"]

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Disable CLAUDE"


async def test_provider_modal_duration_cancel_and_back_paths() -> None:
    snapshot = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"

        modal._on_provider_duration_picked(None)
        await pilot.pause()
        assert pilot.app.screen is modal
        modal._on_provider_duration_picked(providers.DurationChoiceCancelled())
        await pilot.pause()
        assert pilot.app.screen is modal

        modal._on_provider_duration_picked(OPEN_OVERRIDE_UNTIL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, OverrideUntilModal)
        title = pilot.app.screen.query_one("#override-until-title", Static)
        assert title.content == "Disable CLAUDE Until"

        modal._on_provider_until_picked(OVERRIDE_UNTIL_BACK)
        await pilot.pause()
        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Disable CLAUDE"


@pytest.mark.parametrize(
    ("result", "expected_seconds", "expected_until"),
    [
        (RelativeOverrideDuration(30 * 60.0), 30 * 60.0, None),
        (RelativeOverrideDuration(60 * 60.0), 60 * 60.0, None),
        (RelativeOverrideDuration(2 * 60 * 60.0), 2 * 60 * 60.0, None),
        (RelativeOverrideDuration(4 * 60 * 60.0), 4 * 60 * 60.0, None),
        (RelativeOverrideDuration(45 * 60.0), 45 * 60.0, None),
        (OverrideUntilCleared(), None, None),
        (_until_result(), None, 5_000.0),
    ],
)
async def test_provider_modal_disable_accepts_every_duration_result(
    monkeypatch,
    result,
    expected_seconds,
    expected_until,
) -> None:
    before = _snapshot(_status("claude"))
    expires_at = expected_until
    if expires_at is None and expected_seconds is not None:
        expires_at = 100.0 + expected_seconds
    disable = _disable("claude", expires_at=expires_at)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    relative_disable = MagicMock(return_value=disable)
    exact_disable = MagicMock(return_value=disable)
    monkeypatch.setattr(providers, "disable_provider", relative_disable)
    monkeypatch.setattr(providers, "disable_provider_until", exact_disable)
    monkeypatch.setattr(providers, "_now", lambda: 100.0)

    def load_snapshot() -> _ProviderRoutingSnapshot:
        return after if relative_disable.called or exact_disable.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(result)
        await wait_for(pilot, lambda: modal._write_worker is None)

    if expected_until is None:
        relative_disable.assert_called_once_with(
            "claude",
            expected_seconds,
            source="ace",
            now=100.0,
        )
        exact_disable.assert_not_called()
    else:
        exact_disable.assert_called_once_with(
            "claude",
            expected_until,
            source="ace",
            now=100.0,
        )
        relative_disable.assert_not_called()
    assert modal._changed is True
    assert modal._snapshot.provider_disables == {"claude": disable}


async def test_provider_modal_disable_writes_and_refreshes_snapshot(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def load_snapshot() -> _ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    load_snapshot_mock = MagicMock(side_effect=load_snapshot)
    monkeypatch.setattr(providers, "disable_provider", disable_mock)
    monkeypatch.setattr(providers, "_now", lambda: 100.0)
    snapshots: list[_ProviderRoutingSnapshot] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=load_snapshot_mock,
            on_snapshot=lambda snapshot, _provider: snapshots.append(snapshot),
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: modal._changed)

        disable_mock.assert_called_once_with(
            "claude",
            15 * 60.0,
            source="ace",
            now=100.0,
        )
        assert modal._changed is True
        assert snapshots[-1].provider_disables == {"claude": disable}
        modal.notify.assert_any_call(
            "CLAUDE disabled for 15m; alias routing refreshed."
        )


async def test_provider_modal_idempotent_disable_does_not_emit_change(
    monkeypatch,
) -> None:
    before_disable = _disable("claude", expires_at=None)
    after_disable = TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider="claude",
        created_at=200.0,
        expires_at=None,
        source="test",
    )
    before = _snapshot(
        _status("claude", active_disable=before_disable),
        disables={"claude": before_disable},
    )
    after = _snapshot(
        _status("claude", active_disable=after_disable),
        disables={"claude": after_disable},
    )
    disable_mock = MagicMock(return_value=after_disable)
    on_snapshot = MagicMock()
    monkeypatch.setattr(providers, "disable_provider", disable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(OverrideUntilCleared())
        await wait_for(
            pilot,
            lambda: modal._write_worker is None and disable_mock.called,
        )

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "CLAUDE already has that provider disable.",
        severity="warning",
    )


async def test_provider_modal_disable_replacement_with_new_expiry_emits_change(
    monkeypatch,
) -> None:
    before_disable = _disable("claude", expires_at=None)
    after_disable = _disable("claude", expires_at=4_000.0)
    before = _snapshot(
        _status("claude", active_disable=before_disable),
        disables={"claude": before_disable},
    )
    after = _snapshot(
        _status("claude", active_disable=after_disable),
        disables={"claude": after_disable},
    )
    on_snapshot = MagicMock()
    disable_mock = MagicMock(return_value=after_disable)
    monkeypatch.setattr(
        providers,
        "disable_provider",
        disable_mock,
    )

    def load_snapshot() -> _ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=load_snapshot,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(3_900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is True
    on_snapshot.assert_called_once()


async def test_provider_modal_enable_writes_and_refreshes_snapshot(monkeypatch) -> None:
    disable = _disable("claude", expires_at=None)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    after = _snapshot(_status("claude"), disables={})
    enable_mock = MagicMock(return_value=True)
    on_snapshot = MagicMock()
    monkeypatch.setattr(providers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    enable_mock.assert_called_once_with("claude")
    assert modal._changed is True
    on_snapshot.assert_called_once()
    modal.notify.assert_any_call("CLAUDE enabled for new launches.")


async def test_provider_modal_enabled_provider_enable_is_noop(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    enable_mock = MagicMock()
    monkeypatch.setattr(providers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(before, load_snapshot=lambda: before)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.action_enable()
        await pilot.pause()

    enable_mock.assert_not_called()
    assert modal._changed is False
    modal.notify.assert_called_once_with(
        "CLAUDE is already enabled.",
        severity="warning",
    )


async def test_provider_modal_idempotent_enable_does_not_emit_change(
    monkeypatch,
) -> None:
    disable = _disable("claude", expires_at=None)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    enable_mock = MagicMock(return_value=False)
    on_snapshot = MagicMock()
    monkeypatch.setattr(providers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=lambda: before,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "CLAUDE is already enabled.",
        severity="warning",
    )


async def test_provider_modal_write_failure_reports_error(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    on_snapshot = MagicMock()

    def fail_disable(*_args, **_kwargs):
        raise RuntimeError("provider store busy")

    monkeypatch.setattr(providers, "disable_provider", fail_disable)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=lambda: before,
            on_snapshot=on_snapshot,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    assert modal._changed is False
    on_snapshot.assert_not_called()
    modal.notify.assert_any_call(
        "Could not update provider routing: provider store busy",
        severity="error",
    )


def test_provider_modal_snapshot_failure_reports_warning() -> None:
    modal = _ProviderRoutingModal(_snapshot(_status("claude")))
    failed_worker = SimpleNamespace(
        result=None,
        error=RuntimeError("state file locked"),
    )
    modal._snapshot_worker = failed_worker
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal._on_snapshot_worker(
        SimpleNamespace(worker=failed_worker, state=WorkerState.ERROR)
    )

    modal.notify.assert_any_call(
        "Could not load provider routing: state file locked",
        severity="warning",
    )


async def test_provider_modal_cursor_survives_snapshot_refresh() -> None:
    before = _snapshot(_status("claude"), _status("codex"))
    after = _snapshot(_status("claude"), _status("codex", model_count=4))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(before, load_snapshot=lambda: after)
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#provider-routing-list", OptionList)
        option_list.highlighted = option_list.get_option_index("codex")

        modal._apply_snapshot(after, keep_provider="codex", emit_snapshot=False)
        await pilot.pause()

        assert modal._highlighted_provider() == "codex"


def test_provider_modal_unmount_cancels_active_workers() -> None:
    modal = _ProviderRoutingModal(_snapshot(_status("claude")))
    snapshot_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    write_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    modal._snapshot_worker = snapshot_worker
    modal._write_worker = write_worker

    modal.on_unmount()

    snapshot_worker.cancel.assert_called_once_with()
    write_worker.cancel.assert_called_once_with()


def test_panel_ignores_stale_provider_snapshot_worker_event() -> None:
    panel = ModelsPanel()
    current_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    stale_worker = SimpleNamespace(
        result=_snapshot(_status("codex")),
        error=None,
    )
    panel._provider_snapshot_worker = current_worker

    handled = panel._on_provider_snapshot_worker_state(
        SimpleNamespace(worker=stale_worker, state=WorkerState.SUCCESS)
    )

    assert handled is False
    assert panel._provider_snapshot_worker is current_worker
    assert panel._provider_statuses == ()


async def test_panel_expired_provider_disable_refresh_marks_routing_changed_once(
    monkeypatch,
) -> None:
    views = [make_alias_view("default", "default")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("codex", expires_at=100.0)
    before = _snapshot(
        _status("codex", active_disable=disable),
        disables={"codex": disable},
        alias_views=views,
    )
    after = _snapshot(_status("codex"), disables={}, alias_views=views)
    load_snapshot = MagicMock(return_value=after)
    clock = MagicMock(return_value=101.0)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: before,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        panel._apply_provider_snapshot(before, update_rows=True)
        monkeypatch.setattr(panel, "_models_panel_now", clock)
        monkeypatch.setattr(panel, "_load_provider_routing_snapshot", load_snapshot)

        panel._refresh_provider_clock()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        assert panel._changed is True
        assert panel._provider_routing_changed is True
        panel._changed = False
        panel._provider_routing_changed = False
        panel._refresh_provider_clock()
        await pilot.pause()

    load_snapshot.assert_called_once_with()
    assert panel._provider_disables == {}
    assert panel._changed is False
    assert panel._provider_routing_changed is False


async def test_panel_provider_modal_snapshot_rebuilds_rows_and_keeps_cursor(
    monkeypatch,
) -> None:
    before_views = [
        make_alias_view("large_worker", "role"),
        make_alias_view("medium_worker", "role"),
    ]
    after_views = [
        make_alias_view("large_worker", "role", provider="codex", model="o3"),
        make_alias_view("medium_worker", "role", provider="codex", model="o3"),
    ]
    patch_alias_views(monkeypatch, before_views)
    initial_snapshot = _snapshot(_status("codex"), alias_views=before_views)
    snapshot = _snapshot(_status("codex"), alias_views=after_views)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: initial_snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        option_list = panel.query_one("#models-panel-list", OptionList)
        option_list.highlighted = option_list.get_option_index("medium_worker")

        panel._on_provider_modal_snapshot(snapshot, "codex")
        await pilot.pause()

        assert panel._views == after_views
        assert panel._highlighted_row_id() == "medium_worker"
        assert panel._changed is True
        assert panel._provider_routing_changed is True


async def test_models_panel_title_shows_disabled_provider_line(monkeypatch) -> None:
    views = [make_alias_view("default", "default")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("claude", expires_at=None)
    snapshot = _ProviderRoutingSnapshot(
        statuses=(_status("claude", active_disable=disable),),
        provider_disables={"claude": disable},
        alias_views=tuple(views),
        provider_colors={"claude": "#D97757"},
        captured_at=100.0,
    )
    monkeypatch.setattr(providers, "_now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel._apply_provider_snapshot(snapshot, keep="default")
        await pilot.pause()

        title = panel.query_one("#models-panel-title", Static).content.plain
        assert "disabled providers: CLAUDE until cleared" in title
