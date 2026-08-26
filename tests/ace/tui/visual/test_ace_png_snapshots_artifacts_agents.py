"""ACE PNG visual snapshot coverage for Artifacts -> Agent."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import (
    agents_detail_panel,
    agents_pane as agents_pane_module,
)
from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_detail import AgentDetailData
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.agents_query import AgentFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.agents.catalog import AgentCatalogRow
from tests._agent_catalog_helpers import make_agent_catalog_row
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _row(name: str, **overrides: Any) -> AgentCatalogRow:
    defaults: dict[str, Any] = {
        "canonical_global_name": f"bbugyi200.athena.{name}",
        "kind": ("agent",),
        "project": "sase",
        "state": "active",
        "family": None,
        "role": "code",
        "clan": "sase-tj",
        "tribe": "epic",
        "workflow": "code",
        "parent_timestamp": None,
        "raw_suffix": f"20260825-{name.replace('.', '-')}",
        "artifacts_dir": f"/visual/artifacts/{name}",
        "bundle_path": None,
        "model": "gpt-5",
        "llm_provider": "codex",
        "status": "DONE",
        "hidden": False,
        "started_at": "2026-08-25T13:00:00-04:00",
        "finished_at": 1787677500.0,
        "retry_attempt": 0,
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "patch": "sase-tj",
        "dismissed": False,
        "revivable": False,
        "attention": False,
        "retry": False,
        "has_collision_history": False,
        "from_artifact_index": True,
        "from_dismissed_archive": False,
    }
    defaults.update(overrides)
    return make_agent_catalog_row(name, **defaults)


def _populated_rows() -> tuple[AgentCatalogRow, ...]:
    return (
        _row(
            "sase-tj.10",
            kind=("family",),
            family=None,
            role=None,
            workflow="epic",
            status="RUNNING",
            attention=True,
        ),
        _row(
            "sase-tj.10.3",
            family="sase-tj.10",
            role="visual",
            workflow="visual",
            status="RUNNING",
            attention=True,
            started_at="2026-08-25T13:08:00-04:00",
            finished_at=None,
        ),
        _row(
            "sase-tj.10.2",
            family="sase-tj.10",
            role="navigation",
            workflow="code",
            state="done",
            status="DONE",
            started_at="2026-08-25T12:10:00-04:00",
        ),
        _row(
            "sase-tj.audit",
            state="dismissed",
            family=None,
            role="review",
            workflow="review",
            status="FAILED",
            dismissed=True,
            revivable=True,
            attention=True,
            bundle_path="/visual/dismissed/sase-tj.audit.json",
            from_artifact_index=False,
            from_dismissed_archive=True,
            started_at="2026-08-25T11:20:00-04:00",
        ),
    )


def _family_rows() -> tuple[AgentCatalogRow, ...]:
    return (
        _row(
            "visual-family",
            kind=("family",),
            family=None,
            role=None,
            workflow="epic",
            status="RUNNING",
            attention=True,
        ),
        _row(
            "visual-family.plan",
            family="visual-family",
            role="plan",
            workflow="plan",
            status="DONE",
            started_at="2026-08-25T10:00:00-04:00",
        ),
        _row(
            "visual-family.code",
            family="visual-family",
            role="code",
            workflow="code",
            status="RUNNING",
            attention=True,
            started_at="2026-08-25T10:06:00-04:00",
            finished_at=None,
        ),
    )


def _snapshot(rows: tuple[AgentCatalogRow, ...]) -> AgentsSnapshot:
    return AgentsSnapshot(project=None, rows=rows, total_row_count=len(rows))


def _detail_for(row: AgentCatalogRow) -> AgentDetailData:
    return AgentDetailData(
        name=row.name,
        artifacts_dir_live=True,
        resolved_artifacts_dir=row.artifacts_dir,
        prompt_preview=(
            f"# Prompt for {row.name}\n\n"
            "Render the Artifacts Agent pane with deterministic catalog data."
        ),
        prompt_truncated=False,
        chat_path=f"/visual/chats/{row.name}.md",
        page_url=f"https://github.com/sase-org/sase--agents/blob/main/{row.name}.md",
    )


def _install_agents_fixture(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: AgentsSnapshot,
) -> None:
    patch_startup_loaders(monkeypatch)
    first_page = replace(snapshot, complete=False)

    def _load(_project: str | None, limit: int | None = None) -> AgentsSnapshot:
        """Mirror the pane's two-stage loader.

        The bounded first page reports ``complete=False`` so the pane
        schedules its full extension pass, which is what builds the query
        index the filter bar and completion menu render from. Returning the
        fixture snapshot itself for the full pass keeps ``pane.snapshot is
        snapshot`` true once the pane settles.
        """

        return snapshot if limit is None else first_page

    monkeypatch.setattr(agents_pane_module, "load_agents_snapshot", _load)
    monkeypatch.setattr(agents_detail_panel, "load_agent_detail", _detail_for)


async def _open_agents(
    page: AcePage,
    snapshot: AgentsSnapshot,
) -> ArtifactsAgentsPane:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("agents"))
    await page.expect_state("artifacts_subtab", "agents")
    pane = page.query_one_widget("#artifacts-agents-pane", ArtifactsAgentsPane)
    await page.wait_for(
        lambda _state: pane.snapshot is snapshot and pane._query_index is not None
    )
    return pane


async def _select_second_agent(page: AcePage, pane: ArtifactsAgentsPane) -> None:
    before = pane.selected_entry_target()
    await page.press("j")
    await page.wait_for(lambda _state: pane.selected_entry_target() != before)


async def test_artifacts_agents_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(_populated_rows())
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_agents(page, snapshot)
        await _select_second_agent(page, pane)
        detail = pane.query_one("#agents-detail", Static)
        await page.wait_for(
            lambda _state: "Started: 2026-08-25 13:08" in detail.content.plain
        )
        await wait_for_visual_idle(page)

        for token in ("Agent", "Project scope", "RUNNING", "[sase]", "REFERENCE"):
            assert_page_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_populated_120x40",
            title="ACE Artifacts - Agent populated",
        )


async def test_artifacts_agents_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(())
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_agents(page, snapshot)
        await page.wait_for(
            lambda _state: pane.snapshot is snapshot and pane.snapshot.rows == ()
        )
        await wait_for_svg_contains(page, "No agents")
        await wait_for_svg_contains(
            page,
            "No agents match the current project scope and filters.",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_empty_120x40",
            title="ACE Artifacts - Agent empty",
        )


async def test_artifacts_agents_family_grouped_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(_family_rows())
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_agents(page, snapshot)
        await _select_second_agent(page, pane)
        await wait_for_svg_contains(page, "visual-family")
        detail = pane.query_one("#agents-detail", Static)
        await page.wait_for(
            lambda _state: "Started: 2026-08-25 10:00" in detail.content.plain
        )
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-family")
        assert_page_svg_contains(page, "(3)")
        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_family_grouped_120x40",
            title="ACE Artifacts - Agent family grouped",
        )


async def test_artifacts_agents_filter_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(_populated_rows())
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_agents(page, snapshot)
        pane.show_filters()
        bar = pane.query_one(AgentFilterBar)
        bar.open("status:")
        completion = bar.query_one("#agent-filter-completion", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count >= 3
        )
        await wait_for_svg_contains(page, "RUNNING")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_filter_completion_120x40",
            title="ACE Artifacts - Agent filter completion",
        )


async def test_artifacts_agents_filter_parse_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(_populated_rows())
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_agents(page, snapshot)
        bar = pane.query_one(AgentFilterBar)
        await page.press("slash")
        await page.wait_for(lambda _state: bar._editing)  # noqa: SLF001
        bar.query_one("#agent-filter-input", SingleLineVimTextArea).load_text("status:")
        await page.wait_for(
            lambda _state: bar.query_one("#agent-filter-status").has_class("error")
        )
        status = bar.query_one("#agent-filter-status", Static)
        await page.wait_for(
            lambda _state: "Expected property value" in status.content.plain
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_filter_parse_error_120x40",
            title="ACE Artifacts - Agent filter parse error",
        )


async def test_artifacts_agents_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = replace(_snapshot(_populated_rows()), total_row_count=9)
    _install_agents_fixture(monkeypatch, snapshot)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        pane = await _open_agents(page, snapshot)
        await _select_second_agent(page, pane)
        await wait_for_svg_contains(page, "sase-tj.10.3")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_agents_narrow_80x24",
            title="ACE Artifacts - Agent narrow",
        )
