"""Prompt-input dirty flag deferral tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.actions.event_handlers import PROMPT_INPUT_DEFER_SECONDS

from ._event_handlers_dirty_flags_helpers import _FakeApp


def test_auto_refresh_skips_all_background_work_during_prompt_input() -> None:
    """Prompt entry should block axe, notifications, agents, and changespecs."""
    app = _FakeApp(watcher_active=False)
    app._prompt_context = object()
    app._on_auto_refresh()
    assert app.refresh_calls == []
    assert app._countdown_remaining == app.refresh_interval


@pytest.mark.parametrize(
    "context_name",
    ["_approve_prompt_context", "_plan_feedback_context"],
)
def test_auto_refresh_treats_approval_and_feedback_as_prompt_input(
    context_name: str,
) -> None:
    app = _FakeApp(watcher_active=False)
    setattr(app, context_name, object())
    app._on_auto_refresh()
    assert app.refresh_calls == []


def test_auto_refresh_treats_mounted_prompt_bar_as_prompt_input() -> None:
    app = _FakeApp(watcher_active=False)
    app._mounted_prompt_bar = True
    app._on_auto_refresh()
    assert app.refresh_calls == []


def test_artifact_change_defers_refresh_work_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    app._on_artifact_change()
    assert app._dirty_changespecs is True
    assert app._dirty_agents is True
    assert app._dirty_axe is True
    assert app.refresh_calls == []
    assert len(app.deferred_calls) == 1
    delay, callback = app.deferred_calls[0]
    assert delay == PROMPT_INPUT_DEFER_SECONDS
    assert callback == app._on_artifact_change_deferred


def test_artifact_change_preserves_deferred_paths_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    changed = (
        Path.home() / ".sase" / "projects" / "sase" / "artifacts" / "a" / "done.json",
    )

    app._on_artifact_change(changed)

    assert app._artifact_change_deferred_paths == changed

    app._plan_feedback_context = None
    app._on_artifact_change_deferred()

    assert app.refresh_calls == []


def test_artifact_change_dedupes_defer_timers_during_prompt_input() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
    app._on_artifact_change()
    app._on_artifact_change()
    app._on_artifact_change()
    assert len(app.deferred_calls) == 1
    assert app._artifact_change_defer_pending is True
    assert app.refresh_calls == []


def test_artifact_change_deferred_reschedules_while_prompt_still_active() -> None:
    app = _FakeApp(watcher_active=True)
    app._plan_feedback_context = object()
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
    assert "schedule_changespecs" in app.refresh_calls
    assert "schedule_agents" not in app.refresh_calls
    assert app._artifact_change_defer_pending is False
