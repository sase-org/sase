"""Models-panel provider-routing modal drain-plan flow tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal
import sase.ace.tui.modals.models_panel_provider_modal_drain as provider_modal_drain
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.modals.models_panel_duration import RelativeOverrideDuration
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
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
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
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
