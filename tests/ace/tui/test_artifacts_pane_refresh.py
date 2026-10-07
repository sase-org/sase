"""Tick vs explicit refresh for the Beads and Plans panes (sase-1h8.6).

Auto-refresh ticks must not force a reload: the fingerprint-based source
key decides. An explicit user-initiated refresh still forces one.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from sase.ace.tui.actions.artifacts_beads import ArtifactsBeadsActionsMixin
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.lifecycle import ArtifactsPaneLifecycle
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane


def test_beads_pane_tick_does_not_force_and_explicit_forces() -> None:
    calls: list[bool] = []
    pane = SimpleNamespace(_request_load=lambda *, force: calls.append(force))

    ArtifactsBeadsPane.on_refresh(pane)
    ArtifactsBeadsPane.on_explicit_refresh(pane)

    assert calls == [False, True]


def test_plans_pane_tick_does_not_force_and_explicit_forces() -> None:
    calls: list[bool] = []
    pane = SimpleNamespace(_request_load=lambda *, force: calls.append(force))

    ArtifactsPlansPane.on_refresh(pane)
    ArtifactsPlansPane.on_explicit_refresh(pane)

    assert calls == [False, True]


def test_explicit_refresh_defaults_to_tick_behavior() -> None:
    calls: list[str] = []
    pane = SimpleNamespace(on_refresh=lambda: calls.append("tick"))

    ArtifactsPaneLifecycle.on_explicit_refresh(pane)

    assert calls == ["tick"]


def test_beads_post_mutation_completion_requests_explicit_refresh() -> None:
    submit = Mock(return_value=SimpleNamespace(proc_id="task-1"))
    refresh = Mock()
    host = SimpleNamespace(_submit_session_worker=submit)
    pane = SimpleNamespace(request_explicit_refresh=refresh)

    ArtifactsBeadsActionsMixin._submit_beads_task(
        host,
        pane,
        project="sase",
        bead_id="sase-a1",
        operation="note",
        display_name="Add note · sase-a1",
        workspace="/work/sase",
        task=Mock(),
    )

    on_complete = submit.call_args.kwargs["on_complete"]
    on_complete(SimpleNamespace())
    refresh.assert_called_once_with()
