"""Fast-path unread jump tests (epic sase-1d7 phase unread-jump-fast-path)."""

from __future__ import annotations
from types import SimpleNamespace

from datetime import datetime
from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import LeaderUnreadJumpApp, UnreadJumpApp


@pytest.fixture(autouse=True)
def ack_completions(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(
        return_value=SimpleNamespace(dismissed_ids={"n-acked"}, generation=7),
    )
    monkeypatch.setattr(
        "sase.notifications.ack_agent_completions",
        dismiss,
    )
    return dismiss


def _three_unread_app() -> UnreadJumpApp:
    older = make_agent(
        name="older",
        status="DONE",
        raw_suffix="older",
        stop_time=datetime(2026, 5, 7, 10, 0, 0),
    )
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    middle = make_agent(
        name="middle",
        status="FAILED",
        raw_suffix="middle",
        stop_time=datetime(2026, 5, 7, 11, 0, 0),
    )
    app = UnreadJumpApp([older, newest, middle], current_idx=0)
    app._unread_completed_agent_ids.update(
        {older.identity, newest.identity, middle.identity}
    )
    return app


def test_consecutive_jumps_reuse_cached_candidate_list() -> None:
    app = _three_unread_app()
    first = app._unread_timed_jump_candidates()
    assert [c.identity[1] for c in first] == ["newest", "middle", "older"]

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 1

    cached = getattr(app, "_unread_jump_candidates_cache", None)
    assert cached is not None
    # Remove-on-ack: the acked newest is filtered and the key advanced,
    # so the next jump hits without rebuilding.
    assert [c.identity[1] for c in cached[1]] == ["middle", "older"]
    second = app._unread_timed_jump_candidates()
    assert second is cached[1]

    assert app._jump_to_next_unread_done_agent()
    assert app.current_idx == 2
    third = app._unread_timed_jump_candidates()
    assert [c.identity[1] for c in third] == ["older"]


def test_footer_probe_builds_no_jump_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _three_unread_app()
    builds = 0
    real = app._timed_agent_jump_candidates

    def counting(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal builds
        builds += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(app, "_timed_agent_jump_candidates", counting)
    assert app._has_unread_completed_agent() is True
    assert builds == 0
    # Second probe hits the O(1) cache as well.
    assert app._has_unread_completed_agent() is True
    assert builds == 0

    app._unread_completed_agent_ids.clear()
    from sase.ace.tui.actions.agents._unread_set_generation import (
        bump_unread_set_generation,
    )

    bump_unread_set_generation(app)
    assert app._has_unread_completed_agent() is False
    assert builds == 0


def test_collapsed_tribe_jump_rebuilds_only_target_panel() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    target = make_agent(
        name="target",
        status="DONE",
        raw_suffix="target",
        tribe="alpha",
        stop_time=datetime(2026, 7, 16, 15, 0, 0),
    )
    beta = make_agent(name="beta", status="RUNNING", raw_suffix="beta", tribe="beta")
    app = UnreadJumpApp(
        [origin, target, beta],
        current_idx=0,
        with_panels=True,
        focused_key=None,
        collapsed_panels={"alpha"},
    )
    app._unread_completed_agent_ids.add(target.identity)

    assert app._jump_to_next_unread_done_agent()

    assert app._panel_group.focused_key == "alpha"
    assert app.panel_rebuild_calls == [{"alpha"}]
    assert all(not call.get("list_changed") for call in app.refresh_calls)


def test_visible_row_jump_defers_detail_and_stats_no_artifact_dirs() -> None:
    from sase.ace.tui.models.agent import Agent

    app = _three_unread_app()
    artifact_probes = 0
    real_get_dir = Agent.get_artifacts_dir

    def counting_get_dir(self: Agent) -> str | None:
        nonlocal artifact_probes
        artifact_probes += 1
        return real_get_dir(self)

    Agent.get_artifacts_dir = counting_get_dir  # type: ignore[method-assign]
    try:
        assert app._jump_to_next_unread_done_agent()
    finally:
        Agent.get_artifacts_dir = real_get_dir  # type: ignore[method-assign]
    # No artifact-directory probe on the jump tick; any display refresh
    # keeps detail behind the debouncer.
    assert artifact_probes == 0
    assert all(call.get("defer_detail", True) for call in app.refresh_calls)


def test_leader_j_hit_and_miss_skip_trailing_tab_refresh() -> None:
    newest = make_agent(
        name="newest",
        status="DONE",
        raw_suffix="newest",
        tribe="alpha",
        stop_time=datetime(2026, 5, 7, 12, 0, 0),
    )
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = LeaderUnreadJumpApp([running, newest], current_idx=0)
    app._unread_completed_agent_ids.add(newest.identity)

    assert app._handle_leader_key("j") is True
    assert app.current_idx == 1
    assert app.current_tab_refresh_calls == 0
    assert app.refresh_calls == [{"list_changed": False, "defer_detail": True}]

    # Miss only toasts; still no trailing refresh.
    assert app._handle_leader_key("comma") is True
    assert app.notifications == ["No unread completed agents"]
    assert app.current_tab_refresh_calls == 0
