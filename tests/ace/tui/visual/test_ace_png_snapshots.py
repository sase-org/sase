"""ACE TUI PNG visual snapshot coverage for the ChangeSpecs and Agents tabs.

Axe-tab PNG snapshot coverage lives in ``test_ace_png_snapshots_axe``.
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.recursive_finder_modal import RecursiveFileFinderModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupRefWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    changespecs,
    patch_startup_loaders,
    sibling_agents,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = svg.replace("&#160;", " ")
    assert text in svg_plain


async def test_changespec_initial_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.expect_state("selected.name", "visual_auth")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "changespec_initial_120x40",
            title="ACE changespec initial",
        )


async def test_changespec_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("j")
        await page.expect_state("selected.name", "visual_billing")
        page.app._refresh_changespec_detail_only()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "changespec_selected_row_120x40",
            title="ACE changespec selected row",
        )


async def test_query_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "query_edit_modal_120x40",
            title="ACE query edit modal",
        )


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        initial_idx = page.app.current_idx
        for _ in range(8):
            await page.press("j")
            if page.app.current_idx != initial_idx:
                break
        else:
            raise AssertionError("j navigation did not move off the initial agent row")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_selected_row_120x40",
            title="ACE agents selected row",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _zoom_agent(tmp_path: Path) -> Agent:
    diff_path = tmp_path / "visual_zoom.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/src/app.py b/src/app.py",
                "index 1111111..2222222 100644",
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1,5 +1,8 @@",
                " def render_dashboard():",
                "-    return old_summary()",
                "+    summary = build_zoom_summary()",
                "+    summary.enable_live_refresh = True",
                "+    return summary",
                "",
                " def footer_hints():",
                "+    return 'j/k scroll  q close'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-zoom",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 9, 10, 20, 0),
        stop_time=datetime(2026, 5, 9, 10, 28, 45),
        raw_suffix="20260509-102000-zoom",
        agent_name="zoom.snapshot.agent",
        llm_provider="codex",
        model="gpt-5",
        diff_path=str(diff_path),
    )


async def test_agents_file_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_zoom_agent(tmp_path)])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("z")
        await page.expect_modal("ZoomPanelModal")
        await page.pause()
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "agents_file_zoom_modal_120x40",
            title="ACE agents file zoom modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_metadata_zoom_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_zoom_agent(tmp_path)])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("p")
        await page.press("z")
        await page.expect_modal("ZoomPanelModal")
        await page.pause()
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "agents_metadata_zoom_modal_120x40",
            title="ACE agents metadata zoom modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tag="visual",
        ),
    ]


async def _render_leader_footer(page: AcePage) -> None:
    """Force the keybinding footer into LEADER mode and let it lay out.

    LEADER mode is the worst case for footer width — ~15 chips on changespecs
    tab — so it's the right target for grid-overflow snapshots.
    """
    from sase.ace.tui.widgets import KeybindingFooter

    footer = page.app.query_one(KeybindingFooter)
    footer.update_leader_bindings(current_tab="changespecs")
    await wait_for_visual_idle(page)


async def test_footer_leader_overflow_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 120x40: chips overflow into a deterministic grid."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_120x40",
            title="ACE footer LEADER grid (wide)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_footer_leader_overflow_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 80x30: narrower width drops more chips into more rows."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(80, 30)
    ) as page:
        await wait_for_startup(page)
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_80x30",
            title="ACE footer LEADER grid (narrow)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        from sase.ace.tui.widgets import AgentInfoPanel

        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        assert panel._unread_count == 3, f"expected 3 unread, got {panel._unread_count}"
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_sibling_badge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)
        assert page.app._agent_sibling_index().sibling_count(page.app.current_idx) == 2
        _assert_page_svg_contains(page, "siblings: ")

        ace_png_visual.assert_page_png(
            page,
            "agents_sibling_badge_120x40",
            title="ACE agents sibling badge",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agent_sibling_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=sibling_agents())

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app.action_start_sibling_mode()
        await page.expect_modal("AgentSiblingModal")
        await wait_for_visual_idle(page)
        modal = page.app.screen_stack[-1]
        assert modal.__class__.__name__ == "AgentSiblingModal"
        choices = vars(modal)["_choices"]
        assert [choice.global_idx for choice in choices] == [1, 2]
        _assert_page_svg_contains(page, "Sibling Agents: visual family")
        _assert_page_svg_contains(page, "visual.code.implementation.with...")

        ace_png_visual.assert_page_png(
            page,
            "agent_sibling_modal_60x30",
            title="ACE agent sibling modal narrow",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_normal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    recent_groups = tuple(_recent_group_summary(idx) for idx in range(2))
    groups = tuple(_saved_group_summary(idx) for idx in range(3))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=groups, next_cursor=None),
            {},
            recent_page=SavedAgentGroupPageWire(
                groups=recent_groups,
                next_cursor=None,
            ),
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_normal_120x40",
            title="ACE saved agent group modal normal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=(), next_cursor=None),
            {},
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_empty_120x40",
            title="ACE saved agent group modal empty",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_load_more_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    groups = tuple(_saved_group_summary(idx) for idx in range(20))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=groups, next_cursor=20),
            {},
        )
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = len(option_list.options) - 2
        modal._update_preview_for_option_id("load-more")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_load_more_120x40",
            title="ACE saved agent group modal load more",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_saved_agent_group_modal_preview_rich_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    summary = _saved_group_summary(
        0,
        title="6 agents across 3 PRs",
        agent_count=6,
        top_level_agent_count=4,
        status_counts={"DONE": 3, "FAILED": 1, "RUNNING": 2},
        project_names=("sase", "sase-core"),
        cl_names=("backend", "frontend", "regression"),
    )
    group = _saved_group_from_summary(summary, ref_count=6)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _push_saved_group_modal(
            page,
            SavedAgentGroupPageWire(groups=(summary,), next_cursor=None),
            {summary.group_id: group},
        )

        ace_png_visual.assert_page_png(
            page,
            "saved_agent_group_revival_preview_rich_120x40",
            title="ACE saved agent group modal preview-rich",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


def _finder_candidate(rel: str, is_dir: bool = False) -> CompletionCandidate:
    display = f"src/sase/ace/tui/widgets/{rel}"
    if is_dir:
        display += "/"
    return CompletionCandidate(
        display=display,
        insertion=display,
        is_dir=is_dir,
        name=rel.rstrip("/").rsplit("/", 1)[-1],
    )


def _finder_candidates() -> list[CompletionCandidate]:
    """Deterministic finder candidates: 22 match "wi", 2 do not (22/24)."""
    widget_files = [
        "file_completion.py",
        "_file_completion.py",
        "prompt_input_bar.py",
        "prompt_text_area.py",
        "recursive_file_finder.py",
        "directive_completion.py",
        "xprompt_completion.py",
        "xprompt_arg_assist.py",
        "keybinding_footer.py",
        "changespec_detail.py",
        "bgcmd_list.py",
        "agent_info_panel.py",
        "prompt_completion.py",
        "line_rendering.py",
        "vim_normal.py",
        "vim_motions.py",
        "snippets.py",
        "soft_completion.py",
        "history_panel.py",
        "tab_bar.py",
    ]
    candidates = [_finder_candidate(name) for name in widget_files]
    candidates.append(_finder_candidate("file_panel", is_dir=True))
    candidates.append(_finder_candidate("query", is_dir=True))
    # Two entries outside widgets/ that do not contain the "wi" subsequence.
    candidates.append(
        CompletionCandidate(
            display="src/sase/core/episode.py",
            insertion="src/sase/core/episode.py",
            is_dir=False,
            name="episode.py",
        )
    )
    candidates.append(
        CompletionCandidate(
            display="src/sase/db.py",
            insertion="src/sase/db.py",
            is_dir=False,
            name="db.py",
        )
    )
    return candidates


async def test_recursive_finder_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = RecursiveFileFinderModal(
            "src/",
            _finder_candidates(),
            initial_query="wi",
        )
        page.app.push_screen(modal)
        await page.expect_modal("RecursiveFileFinderModal")
        await wait_for_visual_idle(page)
        assert modal._model.match_count == 22
        assert modal._model.total == 24

        ace_png_visual.assert_page_png(
            page,
            "recursive_finder_modal_120x40",
            title="ACE recursive finder modal",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def _push_saved_group_modal(
    page: AcePage,
    initial_page: SavedAgentGroupPageWire,
    groups_by_id: dict[str, SavedAgentGroupWire],
    *,
    recent_page: SavedAgentGroupPageWire | None = None,
) -> SavedAgentGroupRevivalModal:
    modal = SavedAgentGroupRevivalModal(
        initial_page,
        recent_page=recent_page,
        group_loader=groups_by_id.get,
    )
    page.app.push_screen(modal)
    await page.expect_modal("SavedAgentGroupRevivalModal")
    await wait_for_visual_idle(page)
    return modal


def _saved_group_summary(
    idx: int,
    *,
    title: str = "3 agents from @visual",
    agent_count: int = 3,
    top_level_agent_count: int = 2,
    status_counts: dict[str, int] | None = None,
    project_names: tuple[str, ...] = ("sase",),
    cl_names: tuple[str, ...] = ("visual-polish",),
) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"visual-group-{idx:02}",
        created_at=f"May 27 12:{idx:02}",
        source="marked_agents",
        title=title,
        agent_count=agent_count,
        top_level_agent_count=top_level_agent_count,
        status_counts=status_counts or {"DONE": 2, "FAILED": 1},
        project_names=project_names,
        cl_names=cl_names,
    )


def _recent_group_summary(idx: int) -> SavedAgentGroupSummaryWire:
    return SavedAgentGroupSummaryWire(
        group_id=f"recent-visual-group-{idx:02}",
        created_at=f"May 27 12:{idx + 30:02}",
        source="recent_dismissal",
        title="2 agents from @visual",
        agent_count=2,
        top_level_agent_count=2,
        status_counts={"DONE": 2},
        project_names=("sase",),
        cl_names=("visual-polish",),
    )


def _saved_group_from_summary(
    summary: SavedAgentGroupSummaryWire,
    *,
    ref_count: int,
) -> SavedAgentGroupWire:
    refs = tuple(
        SavedAgentGroupRefWire(
            agent_type="run",
            cl_name=("backend", "frontend", "regression")[idx % 3],
            raw_suffix=f"20260527120{idx:02}",
            display_name=f"visual-worker-{idx + 1}",
            agent_name=f"visual.agent.{idx + 1}",
            status=("DONE", "RUNNING", "FAILED")[idx % 3],
            model=("gpt-5", "opus", "flash")[idx % 3],
            llm_provider=("codex", "claude", "gemini")[idx % 3],
        )
        for idx in range(ref_count)
    )
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
        agent_refs=refs,
    )
