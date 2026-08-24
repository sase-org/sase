"""ACE TUI PNG visual snapshots for stand-alone proc shells in the Agents tab.

Stand-alone `%proc` launch units are top-level work rows backed only by the proc
store: they never indent under a family, never take an agent slot, and never
change agent counts. These goldens pin that presentation for mixed agent/proc
rosters, both code languages, every active and terminal state, a long label, a
narrow terminal, and the proc-shell detail composition.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail, AgentInfoPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_agents_proc_shell_png_fixtures import (
    PROC_SHELL_VISUAL_NOW,
    patch_proc_shell_project_names,
    proc_shell_visual_agents,
    seed_proc_shell_projection,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _seeded_agents_tab(page: AcePage) -> None:
    """Open the Agents tab with the deterministic proc-shell projection."""
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    seed_proc_shell_projection(page.app)
    page.app._refresh_agents_display(list_changed=True)
    await wait_for_visual_idle(page)


def _proc_shell_index(page: AcePage, label: str) -> int:
    for index, agent in enumerate(page.app._agents):
        if agent.is_proc_shell and agent.display_name == label:
            return index
    raise AssertionError(f"no proc-shell row labelled {label!r}")


def _assert_procs_are_top_level_rows(page: AcePage) -> None:
    """Procs must be their own kind, not agents wearing a proc costume."""
    proc_rows = [agent for agent in page.app._agents if agent.is_proc_shell]
    assert len(proc_rows) == 7
    for row in proc_rows:
        assert row.is_agent_entry is False
        assert row.parent_workflow is None
        assert row.parent_timestamp is None
        assert row.is_workflow_step_child is False


def _assert_info_header_proc_badge(page: AcePage) -> None:
    info = page.app.query_one("#agent-info-panel", AgentInfoPanel)
    header = info._build_display_text().plain.split("   [view:", 1)[0]

    assert header == "2 agents  [1/10 running · 1 waiting] ⚙7"
    assert header.index("]") < header.index("⚙7")
    assert "procs" not in header
    assert "agents ·" not in header


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "agents_proc_shells_120x40"),
        ((90, 30), "agents_proc_shells_90x30"),
    ],
)
async def test_agents_proc_shell_list_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, PROC_SHELL_VISUAL_NOW)
    patch_proc_shell_project_names(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=proc_shell_visual_agents())

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await _seeded_agents_tab(page)

        _assert_procs_are_top_level_rows(page)
        _assert_info_header_proc_badge(page)
        assert_page_svg_contains(page, "⚙")
        assert_page_svg_contains(page, "❯")
        assert_page_svg_contains(page, "[bash]")
        assert_page_svg_contains(page, "[python]")

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE agents stand-alone proc shells",
        )


async def test_agents_proc_shell_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, PROC_SHELL_VISUAL_NOW)
    patch_proc_shell_project_names(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=proc_shell_visual_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _seeded_agents_tab(page)

        label = "Scoped verification for the typed launch matrix"
        page.app.current_idx = _proc_shell_index(page, label)
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert detail._current_agent is not None
        assert detail._current_agent.is_proc_shell
        rendered = renderable_to_text(prompt.content)
        assert "PROC SHELL" in rendered
        assert "COMMAND" in rendered
        assert "SAFE PREVIEW" not in rendered
        assert rendered.index("COMMAND") < rendered.index("PROC DETAILS")
        assert "just check" in rendered

        # Zoom the summary panel so the golden shows the whole proc-shell
        # detail composition instead of the collapsed side strip.
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "PROC SHELL")

        ace_png_visual.assert_page_png(
            page,
            "agents_proc_shell_detail_120x40",
            title="ACE agents proc-shell detail",
        )
