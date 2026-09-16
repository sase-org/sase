"""ACE hold-confirm preflight: fast path, confirm, and cancel."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.feature_flags import override_flags
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.agent._launch_guard_helpers import install_disables

pytest.importorskip("sase_core_rs")


def test_hold_guard_fast_path_skips_worker_without_hold_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})
    app = _FakeApp()

    app._finish_agent_launch("Plain prompt, no directives.")

    assert app.workers == []
    assert app.pushed_screens == []
    assert len(app.launch_tasks) == 1


def test_hold_guard_skips_modal_for_a_narrow_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})
    app = _FakeApp()

    with override_flags(agent_holds=True):
        app._finish_agent_launch("%hold:planner\nDo work")

    assert len(app.workers) == 1
    assert app.pushed_screens == []
    assert len(app.launch_tasks) == 1


def test_hold_guard_confirms_a_broad_hold_and_launches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})
    app = _FakeApp()

    with override_flags(agent_holds=True):
        app._finish_agent_launch("%hold(future, scope=host)\nDo work")

    assert len(app.pushed_screens) == 1
    screen, callback = app.pushed_screens[0]
    assert isinstance(screen, ConfirmActionModal)
    assert app.launch_tasks == []

    callback(True)

    assert len(app.launch_tasks) == 1


def test_hold_guard_cancel_leaves_the_prompt_bar_mounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})
    app = _FakeApp()

    with override_flags(agent_holds=True):
        app._finish_agent_launch("%hold(future, scope=host)\nDo work")

    _screen, callback = app.pushed_screens[0]
    callback(False)

    assert app.launch_tasks == []
    assert app.unmount_calls == []
    assert app._prompt_context is not None
    assert any("still here" in message for message, _severity in app.notifications)
