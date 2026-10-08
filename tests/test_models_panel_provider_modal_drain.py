"""Automatic provider drain after a manual hard disable tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel_provider_modal as provider_modal
import sase.ace.tui.modals.models_panel_provider_modal_drain as provider_modal_drain
import sase.ace.tui.modals.models_panel_provider_modal_workers as provider_modal_workers
import sase.agent.provider_drain as provider_drain_module
from sase.ace.tui.modals.models_panel_duration import RelativeOverrideDuration
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_MODE_SOFT,
)
from tests._models_panel_helpers import ModelsPanelTestApp, wait_for
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    snapshot as _snapshot,
    status as _status,
)


def _completion(
    *,
    payload=None,
    success: bool = True,
    collision: bool = False,
    proc_id: str = "proc-1",
    message: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        collision=collision,
        success=success,
        payload=payload,
        proc_info=SimpleNamespace(proc_id=proc_id),
        message=message,
    )


def _payload(
    *,
    relaunched: int = 0,
    skipped: int = 0,
    failed: int = 0,
    moves: list[dict] | None = None,
    results: list[dict] | None = None,
    skips: list[dict] | None = None,
    error: dict | None = None,
) -> dict:
    return {
        "counts": {
            "relaunched": relaunched,
            "skipped": skipped,
            "failed": failed,
        },
        "moves": moves or [],
        "results": results or [],
        "skips": skips or [],
        "error": error,
    }


def _move_dict(name: str, target: str) -> dict:
    return {"name": name, "route": {"target_provider": target}}


def _skip_dict(reason: str, detail: str = "", name: str = "sase-xx") -> dict:
    return {
        "name": name,
        "presented_name": name,
        "reason": reason,
        "detail": detail,
    }


async def test_provider_modal_hard_disable_starts_automatic_drain(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider, "on_complete": on_complete})
        return True

    def no_plan(*args, **kwargs):
        raise AssertionError("plan_provider_drain must not run on the write path")

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_drain_module, "plan_provider_drain", no_plan)
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)
    assert not hasattr(provider_modal_workers, "plan_provider_drain")

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.notify = MagicMock()  # type: ignore[method-assign]
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(
            pilot,
            lambda: modal._write_worker is None and len(submitted) == 1,
        )
        await pilot.pause()

        assert submitted[0]["provider"] == "claude"
        assert pilot.app.screen is modal
        titles = [
            call.kwargs.get("title")
            for call in pilot.app.notify.call_args_list
            if "title" in call.kwargs
        ]
        assert "Draining CLAUDE" in titles


async def test_provider_modal_soft_to_hard_transition_drains(monkeypatch) -> None:
    soft = _disable(
        "claude", expires_at=1_000.0, source="ace", mode=PROVIDER_DISABLE_MODE_SOFT
    )
    before = _snapshot(
        _status("claude", active_disable=soft),
        disables={"claude": soft},
    )
    hard = _disable("claude", expires_at=2_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=hard),
        disables={"claude": hard},
    )
    disable_mock = MagicMock(return_value=hard)
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider})
        return True

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(
            pilot, lambda: modal._write_worker is None and len(submitted) == 1
        )

    assert submitted == [{"provider": "claude"}]


async def test_provider_modal_hard_to_hard_window_change_does_not_drain(
    monkeypatch,
) -> None:
    old = _disable("claude", expires_at=1_000.0, source="ace")
    before = _snapshot(
        _status("claude", active_disable=old),
        disables={"claude": old},
    )
    new = _disable("claude", expires_at=2_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=new),
        disables={"claude": new},
    )
    disable_mock = MagicMock(return_value=new)
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider})
        return True

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

        assert submitted == []
        assert pilot.app.screen is modal


async def test_provider_modal_soft_disable_does_not_drain(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    soft = _disable(
        "claude", expires_at=1_000.0, source="ace", mode=PROVIDER_DISABLE_MODE_SOFT
    )
    after = _snapshot(
        _status("claude", active_disable=soft),
        disables={"claude": soft},
    )
    disable_mock = MagicMock(return_value=soft)
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider})
        return True

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_SOFT
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

    assert submitted == []


async def test_provider_modal_flag_off_does_not_drain(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider})
        return True

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: False
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

    assert submitted == []


async def test_provider_modal_unchanged_write_does_not_drain(monkeypatch) -> None:
    before = _snapshot(_status("claude"))
    disable_mock = MagicMock(return_value=_disable("claude", expires_at=1_000.0))
    submitted: list[dict] = []

    def fake_submit(_app, *, provider, on_complete=None):
        submitted.append({"provider": provider})
        return True

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

    assert submitted == []


async def test_provider_modal_drain_submit_false_shows_no_start_toast(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def fake_submit(_app, *, provider, on_complete=None):
        return False

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.notify = MagicMock()  # type: ignore[method-assign]
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

        start_toasts = [
            call
            for call in pilot.app.notify.call_args_list
            if call.kwargs.get("title") == "Draining CLAUDE"
        ]
        assert start_toasts == []


async def test_provider_modal_drain_submit_raises_shows_error_toast(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0, source="ace")
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    disable_mock = MagicMock(return_value=disable)

    def fake_submit(_app, *, provider, on_complete=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(provider_modal_workers, "disable_provider", disable_mock)
    monkeypatch.setattr(
        provider_modal_workers, "_provider_drain_flag_enabled", lambda: True
    )
    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    monkeypatch.setattr(provider_modal, "now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.notify = MagicMock()  # type: ignore[method-assign]
        modal = ProviderRoutingModal(
            before, load_snapshot=lambda: after if disable_mock.called else before
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._pending_provider = "claude"
        modal._pending_mode = PROVIDER_DISABLE_MODE_HARD
        modal._submit_disable(RelativeOverrideDuration(900.0))
        await wait_for(pilot, lambda: modal._write_worker is None)
        await pilot.pause()

        messages = [str(call.args[0]) for call in pilot.app.notify.call_args_list]
        assert any("Could not start the CLAUDE drain: boom" in m for m in messages)


async def _drive_completion(monkeypatch, fake_completion: SimpleNamespace):
    """Start one automatic drain and drive its captured on_complete."""
    before = _snapshot(_status("claude"))
    captured: dict = {}

    def fake_submit(_app, *, provider, on_complete=None):
        captured["on_complete"] = on_complete
        return True

    monkeypatch.setattr(provider_modal_drain, "submit_provider_drain", fake_submit)
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.notify = MagicMock()  # type: ignore[method-assign]
        modal = ProviderRoutingModal(before, load_snapshot=lambda: before)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._start_provider_drain("claude")
        assert captured["on_complete"] is not None
        captured["on_complete"](fake_completion)
        return pilot.app.notify


async def test_drain_completion_relaunched_with_providers_and_skips(
    monkeypatch,
) -> None:
    payload = _payload(
        relaunched=3,
        skipped=1,
        moves=[
            _move_dict("sase-aa", "codex"),
            _move_dict("sase-bb", "codex"),
            _move_dict("sase-cc", "gemini"),
        ],
        results=[
            {"name": "sase-aa", "status": "ok"},
            {"name": "sase-bb", "status": "ok"},
            {"name": "sase-cc", "status": "ok"},
        ],
        skips=[_skip_dict("pending_question", "", name="sase-dd")],
    )
    notify = await _drive_completion(
        monkeypatch, _completion(payload=payload, success=True)
    )
    assert notify.call_count >= 2
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "information"
    assert kwargs["title"] == "CLAUDE drained"
    assert "Relaunched 3 agents on CODEX and GEMINI" in _args[0]
    assert "1 agent left alone (1 waiting on a question)" in _args[0]


async def test_drain_completion_failures(monkeypatch) -> None:
    payload = _payload(
        relaunched=2,
        skipped=1,
        failed=1,
        moves=[
            _move_dict("sase-aa", "codex"),
            _move_dict("sase-bb", "codex"),
            _move_dict("sase-cc", "codex"),
        ],
        results=[
            {"name": "sase-aa", "status": "ok"},
            {"name": "sase-bb", "status": "ok"},
            {"name": "sase-cc", "status": "fail", "error": "restart blew up"},
        ],
        skips=[_skip_dict("pending_question", "", name="sase-dd")],
    )
    notify = await _drive_completion(
        monkeypatch, _completion(payload=payload, success=True)
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "error"
    assert kwargs["title"] == "CLAUDE drain finished with failures"
    assert "1 agent failed" in _args[0]
    assert "Inspect proc proc-1 in Procs." in _args[0]


async def test_drain_completion_skips_only(monkeypatch) -> None:
    payload = _payload(
        skipped=2,
        skips=[
            _skip_dict("pending_question", "", name="sase-aa"),
            _skip_dict(
                "stranded", "pinned to claude/opus; not reachable", name="sase-bb"
            ),
        ],
    )
    notify = await _drive_completion(
        monkeypatch, _completion(payload=payload, success=True)
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "warning"
    assert kwargs["title"] == "CLAUDE drain: nothing could move"
    assert "2 agents left alone" in _args[0]
    assert "waiting on a question" in _args[0]
    assert "pinned to claude/opus" in _args[0]


async def test_drain_completion_nothing_at_all(monkeypatch) -> None:
    notify = await _drive_completion(
        monkeypatch, _completion(payload=_payload(), success=True)
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "information"
    assert kwargs["title"] == "CLAUDE drain done"
    assert "No agents depended on CLAUDE; nothing to relaunch." in _args[0]


async def test_drain_completion_not_disabled(monkeypatch) -> None:
    payload = _payload(error={"reason": "not_disabled", "message": "gone"})
    notify = await _drive_completion(
        monkeypatch, _completion(payload=payload, success=True)
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "information"
    assert "no longer hard-disabled" in _args[0]


async def test_drain_completion_collision(monkeypatch) -> None:
    notify = await _drive_completion(
        monkeypatch, _completion(payload=None, collision=True)
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "warning"
    assert "already running" in _args[0]
    assert "check Procs" in _args[0]


async def test_drain_completion_missing_payload_with_failure(monkeypatch) -> None:
    notify = await _drive_completion(
        monkeypatch,
        _completion(payload=None, success=False, proc_id="proc-9", message="boom"),
    )
    _args, kwargs = notify.call_args
    assert kwargs["severity"] == "error"
    assert kwargs["title"] == "CLAUDE drain failed"
    assert "proc-9" in _args[0]
    assert "boom" in _args[0]


def test_skip_reason_grouping_matches_prompt_labels() -> None:
    skips = [
        _skip_dict("stranded", "pinned to claude/opus; not reachable", name="a"),
        _skip_dict("pending_question", "", name="b"),
        _skip_dict("monitor", "", name="c"),
        _skip_dict("caller", "", name="d"),
        _skip_dict("capped", "", name="e"),
        _skip_dict("weird_reason", "", name="f"),
    ]
    breakdown = provider_modal_drain._skip_breakdown(skips)
    assert "1 pinned to claude/opus" in breakdown
    assert "1 waiting on a question" in breakdown
    assert "1 monitor row" in breakdown
    assert "1 current agent" in breakdown
    assert "1 over the drain limit" in breakdown
    assert "1 weird reason" in breakdown


def test_ok_target_providers_join_with_and() -> None:
    payload = _payload(
        relaunched=3,
        moves=[
            _move_dict("sase-aa", "codex"),
            _move_dict("sase-bb", "gemini"),
            _move_dict("sase-cc", "codex"),
        ],
        results=[
            {"name": "sase-aa", "status": "ok"},
            {"name": "sase-bb", "status": "ok"},
            {"name": "sase-cc", "status": "fail"},
        ],
    )
    assert provider_modal_drain._ok_target_providers(payload) == ["CODEX", "GEMINI"]
    assert provider_modal_drain._join_and(["CODEX"]) == "CODEX"
    assert provider_modal_drain._join_and(["CODEX", "GEMINI"]) == "CODEX and GEMINI"
    assert provider_modal_drain._join_and(["A", "B", "C"]) == "A, B, and C"


def test_provider_modal_drain_completion_toast_covers_counts() -> None:
    title, message, severity = provider_modal_drain._drain_completion_toast(
        "claude",
        _completion(
            payload=_payload(relaunched=4, skipped=1),
            success=True,
        ),
    )
    assert title == "CLAUDE drained"
    assert severity == "information"
    assert message == "Relaunched 4 agents; 1 agent left alone."
