"""ACE TUI PNG visual snapshot coverage."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _changespecs() -> list[Any]:
    return [
        make_changespec(
            name="visual_auth",
            description="Adds deterministic login review coverage.",
            status="Ready",
            cl=None,
            parent="root_plan",
            file_path="/tmp/visual_project.gp",
        ),
        make_changespec(
            name="visual_billing",
            description="Exercises the selected row visual state.",
            status="Draft",
            cl=None,
            parent="visual_auth",
            file_path="/tmp/visual_project.gp",
        ),
        make_changespec(
            name="visual_cli",
            description="Keeps the list tall enough for stable layout.",
            status="WIP",
            cl=None,
            parent=None,
            file_path="/tmp/visual_project.gp",
        ),
    ]


def _agents() -> list[Agent]:
    started = datetime(2026, 5, 9, 10, 0, 0)
    stopped = datetime(2026, 5, 9, 10, 7, 30)
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.gp",
            status="DONE",
            start_time=started,
            stop_time=stopped,
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.gp",
            status="FAILED",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
            error_message="focused fixture failure",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.gp",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


def _patch_startup_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    agents: list[Agent] | None = None,
) -> None:
    """Replace background startup data sources with deterministic fixtures."""
    import sase.notifications as notifications
    from sase.ace.tui.actions.agents import _loading

    state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    def _fake_load_agents(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            all_agents=list(agents or []),
            dismissed_from_loader=[],
            load_state=state,
        )

    async def _fake_axe_startup(app: AceApp) -> None:
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

    def _fake_notification_snapshot(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            notifications=[],
            expired_ids=[],
            counts=SimpleNamespace(priority=1, rest=18, muted=0, errors=0),
        )

    monkeypatch.setattr(_loading, "load_agents_from_disk_with_state", _fake_load_agents)
    monkeypatch.setattr(AceApp, "_run_axe_startup_init", _fake_axe_startup)
    monkeypatch.setattr(
        notifications,
        "read_notification_snapshot",
        _fake_notification_snapshot,
    )


async def _wait_for_startup(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: (
            page.app._agents_first_load_done and page.app._axe_first_load_done
        )
    )


async def test_changespec_initial_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=_changespecs()) as page:
        await _wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.expect_state("selected.name", "visual_auth")

        ace_png_visual.assert_page_png(
            page,
            "changespec_initial_120x40",
            title="ACE changespec initial",
        )


async def test_changespec_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=_changespecs()) as page:
        await _wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("j")
        await page.expect_state("selected.name", "visual_billing")

        ace_png_visual.assert_page_png(
            page,
            "changespec_selected_row_120x40",
            title="ACE changespec selected row",
        )


async def test_query_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=_changespecs()) as page:
        await _wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        ace_png_visual.assert_page_png(
            page,
            "query_edit_modal_120x40",
            title="ACE query edit modal",
        )


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_startup_loaders(monkeypatch, agents=_agents())

    async with AcePage(query='"visual"', changespecs=_changespecs()) as page:
        await _wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
        )
