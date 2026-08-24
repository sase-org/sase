"""Models-panel provider-routing modal tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from textual.widgets import OptionList, Static
from textual.worker import WorkerState

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal
import sase.ace.tui.modals.models_panel_provider_modal_drain as provider_modal_drain
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
from sase.ace.tui.modals.duration_choice_modal import DurationChoiceCancelled
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    DurationPickerModal,
    KeepCurrentWindow,
    OverrideUntilCleared,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
)
from sase.ace.tui.modals.provider_drain_prompt_modal import (
    ProviderDrainPromptDecision,
    ProviderDrainPromptModal,
)
from sase.agent.provider_drain import (
    DrainRoute,
    ProviderDrainMove,
    ProviderDrainPlan,
    ProviderDrainSkip,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
    until_result as _until_result,
)


def _drain_move(name: str = "sase-aa") -> ProviderDrainMove:
    return ProviderDrainMove(
        name=name,
        presented_name=name,
        project="sase",
        status="RUNNING",
        route=DrainRoute(
            kind="reroute",
            target_provider="codex",
            target_model="gpt-5",
        ),
        restart_plan=SimpleNamespace(),  # type: ignore[arg-type]
    )


def _drain_plan(
    *,
    moves: tuple[ProviderDrainMove, ...] = (),
    skips: tuple[ProviderDrainSkip, ...] = (),
) -> ProviderDrainPlan:
    return ProviderDrainPlan(
        provider="claude",
        disable=_disable("claude", expires_at=1_000.0, source="ace"),
        moves=moves,
        skips=skips,
        model_override=None,
        limit=20,
    )


async def test_provider_modal_initial_snapshot_does_not_emit_change() -> None:
    before = _snapshot(_status("claude"))
    after = _snapshot(_status("claude"), disables={})
    on_snapshot = MagicMock()

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after,
            on_snapshot=on_snapshot,
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._snapshot is after)

    assert modal._changed is False
    on_snapshot.assert_not_called()


async def test_provider_modal_omits_hidden_provider_and_opens_duration() -> None:
    snapshot = _snapshot(
        _status("claude"),
        _status("fakey", hidden=True),
        _status("codex", cli_available=False),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
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
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"

        modal._on_provider_duration_picked(None)
        await pilot.pause()
        assert pilot.app.screen is modal
        modal._on_provider_duration_picked(DurationChoiceCancelled())
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
    monkeypatch.setattr(provider_modal_workers, "disable_provider", relative_disable)
    monkeypatch.setattr(provider_modal_workers, "disable_provider_until", exact_disable)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if relative_disable.called or exact_disable.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
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
            mode=PROVIDER_DISABLE_MODE_HARD,
            now=100.0,
        )
        exact_disable.assert_not_called()
    else:
        exact_disable.assert_called_once_with(
            "claude",
            expected_until,
            source="ace",
            mode=PROVIDER_DISABLE_MODE_HARD,
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

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    load_snapshot_mock = MagicMock(side_effect=load_snapshot)
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)
    snapshots: list[ProviderRoutingSnapshot] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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
            mode=PROVIDER_DISABLE_MODE_HARD,
            now=100.0,
        )
        assert modal._changed is True
        assert snapshots[-1].provider_disables == {"claude": disable}
        modal.notify.assert_any_call(
            "CLAUDE disabled for 15m; alias routing refreshed."
        )


async def test_provider_modal_hard_disable_prompts_for_drain_preview(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    plan = _drain_plan(moves=(_drain_move(),))
    plan_mock = MagicMock(return_value=plan)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal_workers, "plan_provider_drain", plan_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(
            pilot,
            lambda: (
                modal._write_worker is None
                and isinstance(pilot.app.screen, ProviderDrainPromptModal)
            ),
        )

    plan_mock.assert_called_once_with("claude", limit=20, now=100.0)


async def test_provider_modal_empty_drain_preview_stays_silent(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers,
        "plan_provider_drain",
        MagicMock(return_value=_drain_plan()),
    )
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after if disable_mock.called else before,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

        assert pilot.app.screen is modal


async def test_provider_modal_soft_disable_does_not_plan_drain(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable(
        "claude",
        expires_at=1_000.0,
        source="ace",
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    plan_mock = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal_workers, "plan_provider_drain", plan_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after if disable_mock.called else before,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_SOFT
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    plan_mock.assert_not_called()


async def test_provider_modal_flag_off_does_not_plan_drain(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    plan_mock = MagicMock()
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal_workers, "plan_provider_drain", plan_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: False
    )
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before,
            load_snapshot=lambda: after if disable_mock.called else before,
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)

    plan_mock.assert_not_called()


async def test_provider_modal_relaunch_decision_submits_drain(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    submitted: list[dict[str, object]] = []

    def fake_submit(_app, *, provider, model=None, on_complete=None):
        del on_complete
        submitted.append({"provider": provider, "model": model})
        return True

    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal._on_provider_drain_decision(
            _drain_plan(moves=(_drain_move(),)),
            ProviderDrainPromptDecision(action="relaunch"),
        )

    assert submitted == [{"provider": "claude", "model": None}]
    modal.notify.assert_any_call("Drain submitted for CLAUDE; watch Procs.")


async def test_provider_modal_model_decision_opens_picker() -> None:
    before = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal._on_provider_drain_decision(
            _drain_plan(moves=(_drain_move(),)),
            ProviderDrainPromptDecision(action="pick_model"),
        )
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelPickerModal)


def test_provider_modal_drain_completion_message_uses_counts() -> None:
    assert (
        provider_modal_drain._drain_completion_message(
            {"counts": {"relaunched": 4, "skipped": 1, "failed": 0}}
        )
        == "Relaunched 4 agents; 1 left alone"
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
    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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
        provider_modal_workers,
        "disable_provider",
        disable_mock,
    )

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
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
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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

    monkeypatch.setattr(provider_modal_workers, "disable_provider", fail_disable)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
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
    modal = ProviderRoutingModal(_snapshot(_status("claude")))
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
        modal = ProviderRoutingModal(before, load_snapshot=lambda: after)
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#provider-routing-list", OptionList)
        option_list.highlighted = option_list.get_option_index("codex")

        modal._apply_snapshot(after, keep_provider="codex", emit_snapshot=False)
        await pilot.pause()

        assert modal._highlighted_provider() == "codex"


def test_provider_modal_unmount_cancels_active_workers() -> None:
    modal = ProviderRoutingModal(_snapshot(_status("claude")))
    snapshot_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    write_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    modal._snapshot_worker = snapshot_worker
    modal._write_worker = write_worker

    modal.on_unmount()

    snapshot_worker.cancel.assert_called_once_with()
    write_worker.cancel.assert_called_once_with()


async def test_provider_modal_s_writes_soft_disable_with_picked_duration(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, mode=PROVIDER_DISABLE_MODE_SOFT)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if disable_mock.called else before

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Soft-disable CLAUDE"
        keys = [choice.key for choice in pilot.app.screen._choices]
        assert "x" not in keys

        await pilot.press("4")
        await wait_for(pilot, lambda: modal._changed)

    disable_mock.assert_called_once_with(
        "claude",
        2 * 60 * 60.0,
        source="ace",
        mode=PROVIDER_DISABLE_MODE_SOFT,
        now=100.0,
    )
    modal.notify.assert_any_call(
        "CLAUDE soft-disabled for 2h; alias routing refreshed."
    )


async def test_provider_modal_d_on_soft_row_offers_keep_current_window(
    monkeypatch,
) -> None:
    disable = _disable(
        "claude",
        expires_at=6_220.0,
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    flipped = _disable("claude", expires_at=6_220.0)
    after = _snapshot(
        _status("claude", active_disable=flipped),
        disables={"claude": flipped},
    )
    exact_disable = MagicMock(return_value=flipped)

    def load_snapshot() -> ProviderRoutingSnapshot:
        return after if exact_disable.called else before

    monkeypatch.setattr(provider_modal_workers, "disable_provider_until", exact_disable)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=load_snapshot)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()
        picker = pilot.app.screen
        assert isinstance(picker, DurationPickerModal)
        assert picker._choices[0].key == "x"
        assert isinstance(picker._choices[0].value, KeepCurrentWindow)
        assert picker._choices[0].value.expires_at == 6_220.0
        assert "Keep current window" in picker._choices[0].title

        await pilot.press("x")
        await wait_for(pilot, lambda: modal._changed)

    exact_disable.assert_called_once_with(
        "claude",
        6_220.0,
        source="ace",
        mode=PROVIDER_DISABLE_MODE_HARD,
        now=100.0,
    )
    modal.notify.assert_any_call(
        "CLAUDE disabled with its current window (was soft); alias routing refreshed."
    )


async def test_provider_modal_s_on_soft_row_does_not_offer_keep_current() -> None:
    disable = _disable("claude", expires_at=6_220.0, mode=PROVIDER_DISABLE_MODE_SOFT)
    snapshot = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        picker = pilot.app.screen
        assert isinstance(picker, DurationPickerModal)
        assert [choice.key for choice in picker._choices][0] == "1"
        assert "x" not in [choice.key for choice in picker._choices]


async def test_provider_modal_x_clears_soft_disable(monkeypatch) -> None:
    disable = _disable("claude", expires_at=None, mode=PROVIDER_DISABLE_MODE_SOFT)
    before = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    after = _snapshot(_status("claude"), disables={})
    enable_mock = MagicMock(return_value=True)
    monkeypatch.setattr(provider_modal_workers, "enable_provider", enable_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: after)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._submit_enable("claude")
        await wait_for(pilot, lambda: modal._write_worker is None)

    enable_mock.assert_called_once_with("claude")
    assert modal._changed is True
    modal.notify.assert_any_call("CLAUDE enabled for new launches.")


async def test_provider_modal_footer_names_soft_disable() -> None:
    snapshot = _snapshot(_status("claude"))

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()
        footer = modal.query_one("#provider-routing-footer", Static)
        assert "Soft disable" in str(footer.content)
        assert "d/enter" in str(footer.content)
