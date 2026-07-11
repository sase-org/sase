"""Routing tests for saved agent group revival."""

from __future__ import annotations

from typing import Any
from unittest.mock import call, patch

from sase.ace.tui.modals import DismissedAgentSelectModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupPageWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)

from tests._agent_revive_helpers import FakeReviveApp, make_agent


class _ScreenCapture:
    def __init__(self) -> None:
        self.pushed: list[tuple[object, Any]] = []

    def push_screen(self, screen: object, callback: Any = None) -> None:
        self.pushed.append((screen, callback))


def test_agents_r_opens_saved_group_revival_panel() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch(
            "sase.ace.dismissed_agents.list_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
        patch(
            "sase.ace.dismissed_agents.list_recent_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
    ):
        app._revive_agent()

    assert len(capture.pushed) == 1
    assert isinstance(capture.pushed[0][0], SavedAgentGroupRevivalModal)


def test_custom_search_result_opens_unscoped_dismissed_archive() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}

    with (
        patch(
            "sase.ace.dismissed_agents.list_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(
                groups=(_summary(),), next_cursor=None
            ),
        ),
        patch(
            "sase.ace.dismissed_agents.list_recent_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
    ):
        app._revive_agent()

    callback = capture.pushed[0][1]
    callback(SavedAgentGroupRevivalResult(action="custom_search"))

    assert len(capture.pushed) == 2
    assert isinstance(capture.pushed[1][0], DismissedAgentSelectModal)


def test_custom_search_pages_global_archive_and_revives_without_scope() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    recent = make_agent(cl_name="recent", raw_suffix="20260527130000")
    older = make_agent(cl_name="older", raw_suffix="20260527120000")
    oldest = make_agent(cl_name="oldest", raw_suffix="20260527110000")
    app._dismissed_agent_objects = [recent]
    revived_single: list[object] = []
    revived_batches: list[list[object]] = []
    app._do_revive_agent = revived_single.append  # type: ignore[method-assign]
    app._do_revive_agents = revived_batches.append  # type: ignore[method-assign]

    with patch(
        "sase.ace.dismissed_agents.load_dismissed_bundles_page",
        side_effect=[([older], False), ([oldest], True)],
    ) as load_page:
        app._open_custom_revival_search()
        modal = capture.pushed[0][0]
        assert isinstance(modal, DismissedAgentSelectModal)
        assert modal._page_loader is not None

        first_visible, _, first_exhausted = modal._page_loader()
        second_visible, _, second_exhausted = modal._page_loader()

    assert load_page.call_args_list == [
        call(limit=250, offset=0),
        call(limit=250, offset=250),
    ]
    assert {agent.identity for agent in first_visible} == {
        recent.identity,
        older.identity,
    }
    assert {agent.identity for agent in second_visible} == {
        recent.identity,
        older.identity,
        oldest.identity,
    }
    assert not first_exhausted
    assert second_exhausted

    selection_callback = capture.pushed[0][1]
    selection_callback([recent])
    selection_callback([older, oldest])

    assert revived_single == [recent]
    assert revived_batches == [[older, oldest]]


def test_saved_group_result_dispatches_to_phase_four_hook() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    agent = make_agent()
    app._dismissed_agent_objects = [agent]
    app._dismissed_agents = {agent.identity}
    revived_group_ids: list[str] = []
    app._revive_saved_agent_group = revived_group_ids.append  # type: ignore[method-assign]

    with (
        patch(
            "sase.ace.dismissed_agents.list_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(
                groups=(_summary(),), next_cursor=None
            ),
        ),
        patch(
            "sase.ace.dismissed_agents.list_recent_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
    ):
        app._revive_agent()

    callback = capture.pushed[0][1]
    callback(
        SavedAgentGroupRevivalResult(
            action="revive_group",
            group_id="group-a",
        )
    )

    assert revived_group_ids == ["group-a"]


def test_recent_group_result_dispatches_with_recent_location() -> None:
    app = FakeReviveApp()
    capture = _ScreenCapture()
    app.app = capture  # type: ignore[attr-defined]
    revived: list[tuple[str, str]] = []

    def revive(group_id: str, *, location: str = "saved") -> None:
        revived.append((group_id, location))

    app._revive_saved_agent_group = revive  # type: ignore[method-assign]

    with (
        patch(
            "sase.ace.dismissed_agents.list_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(groups=(), next_cursor=None),
        ),
        patch(
            "sase.ace.dismissed_agents.list_recent_dismissed_agent_groups",
            return_value=SavedAgentGroupPageWire(
                groups=(_recent_summary(),), next_cursor=None
            ),
        ),
        patch(
            "sase.ace.dismissed_agents.load_recent_dismissed_agent_group",
            return_value=_recent_group(),
        ),
    ):
        app._revive_agent()

    callback = capture.pushed[0][1]
    callback(
        SavedAgentGroupRevivalResult(
            action="revive_group",
            group_id="recent-a",
            location="recent",
        )
    )

    assert revived == [("recent-a", "recent")]


def _summary() -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id="group-a",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="1 agent in backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _recent_summary() -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id="recent-a",
        created_at="2026-05-27T12:30:00Z",
        source="recent_dismissal",
        title="1 agent in backend",
        agent_count=1,
        top_level_agent_count=1,
        status_counts={"DONE": 1},
        project_names=("sase",),
        cl_names=("backend",),
    )


def _recent_group() -> SavedAgentGroupWire:
    summary = _recent_summary()
    return SavedAgentGroupWire(
        group_id=summary.group_id,
        created_at=summary.created_at,
        source=summary.source,
        title=summary.title,
        agent_count=summary.agent_count,
        top_level_agent_count=summary.top_level_agent_count,
        status_counts=summary.status_counts,
        project_names=summary.project_names,
        cl_names=summary.cl_names,
        agent_refs=(
            SavedAgentGroupRefWire(
                agent_type="run",
                cl_name="backend",
                raw_suffix="recent-suffix",
            ),
        ),
    )
