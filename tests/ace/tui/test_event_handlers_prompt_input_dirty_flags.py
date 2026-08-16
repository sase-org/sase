"""Prompt-input dirty flag deferral tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions.event_handlers import PROMPT_INPUT_DEFER_SECONDS

from ._event_handlers_dirty_flags_helpers import _FakeApp


def test_stale_prompt_context_alone_does_not_block_auto_refresh() -> None:
    app = _FakeApp(watcher_active=False)
    app._prompt_context = object()
    app._spawn_auto_refresh_task = lambda: app.refresh_calls.append("spawn")  # type: ignore[method-assign]
    app._on_auto_refresh()
    assert app.refresh_calls == ["spawn"]


@pytest.mark.parametrize(
    "context_name",
    ["_prompt_context", "_approve_prompt_context", "_plan_feedback_context"],
)
def test_stale_prompt_contexts_do_not_latch_action_or_refresh_gates(
    context_name: str,
) -> None:
    app = _FakeApp(watcher_active=False)
    setattr(app, context_name, object())
    app._screen_stack = [object()]
    app.screen = object()
    app._spawn_auto_refresh_task = lambda: app.refresh_calls.append("spawn")  # type: ignore[method-assign]

    app._on_auto_refresh()
    assert app.refresh_calls == ["spawn"]
    assert (
        check_app_action(app, "start_agent_from_patch", (), lambda *_args: True)
        is not False
    )
    assert check_app_action(app, "search_forward", (), lambda *_args: True) is not False


def test_auto_refresh_treats_mounted_prompt_bar_as_prompt_input() -> None:
    app = _FakeApp(watcher_active=False)
    app._mounted_prompt_bar = True
    app._on_auto_refresh()
    assert app.refresh_calls == []


def test_auto_refresh_treats_editor_suspend_as_prompt_input() -> None:
    app = _FakeApp(watcher_active=False)
    app._prompt_editor_suspended = True
    app._on_auto_refresh()
    assert app.refresh_calls == []


def test_artifact_change_defers_refresh_work_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._mounted_prompt_bar = True
    app._on_artifact_change()
    assert app._dirty_patches is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    assert delay == PROMPT_INPUT_DEFER_SECONDS
    assert callback == app._on_artifact_change_deferred


def test_artifact_change_preserves_deferred_paths_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._mounted_prompt_bar = True
    changed = (
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "a" / "done.json",
    )

    app._on_artifact_change(changed)

    assert app._artifact_change_deferred_paths == changed

    app._mounted_prompt_bar = False
    app._on_artifact_change_deferred()

    assert app.refresh_calls == []


def test_artifact_change_dedupes_defer_timers_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._mounted_prompt_bar = True
    app._on_artifact_change()
    app._on_artifact_change()
    app._on_artifact_change()
    assert len(app.deferred_calls) == 1
    assert app._artifact_change_defer_pending is True
    assert app.refresh_calls == []


def test_artifact_change_deferred_reschedules_while_prompt_still_active() -> None:
    app = _FakeApp(watcher_active=True)
    app._mounted_prompt_bar = True
    app._artifact_change_defer_pending = True
    app._on_artifact_change_deferred()
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    assert delay == PROMPT_INPUT_DEFER_SECONDS
    assert callback == app._on_artifact_change_deferred
    assert app._artifact_change_defer_pending is True
    assert app.refresh_calls == []


def test_artifact_change_deferred_resumes_refresh_after_prompt_closes() -> None:
    app = _FakeApp(watcher_active=True)
    app._artifact_change_defer_pending = True
    app._on_artifact_change_deferred()
    assert "schedule_patches" in app.refresh_calls
    assert "schedule_agents" not in app.refresh_calls
    assert app._artifact_change_defer_pending is False
