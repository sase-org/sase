"""sase's TUI PNG visual snapshots for stand-alone named procs in the Agents tab.

Stand-alone `%proc` launch units are top-level work rows backed only by the proc
store: they never indent under a session, never take an agent slot, and never
change agent counts. These goldens pin that presentation for mixed agent/proc
rosters, both code languages, every active and terminal state, a long label, a
narrow terminal, and the named-proc detail composition.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail, AgentInfoPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
    prompt_header_and_body_text,
)
from tests.ace.tui.visual._ace_agents_named_proc_png_fixtures import (
    PROC_TURN_VISUAL_NOW,
    patch_named_proc_project_names,
    named_proc_visual_agents,
    seed_named_proc_projection,
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
    """Open the Agents tab with the deterministic named-proc projection."""
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    seed_named_proc_projection(page.app)
    page.app._refresh_agents_display(list_changed=True)
    await wait_for_visual_idle(page)


def _named_proc_index(page: AcePage, label: str) -> int:
    for index, agent in enumerate(page.app._agents):
        if agent.is_named_proc and agent.display_name == label:
            return index
    raise AssertionError(f"no named-proc row labelled {label!r}")


def _assert_procs_are_top_level_rows(page: AcePage) -> None:
    """Procs must be their own kind, not agents wearing a proc costume."""
    proc_rows = [agent for agent in page.app._agents if agent.is_named_proc]
    assert len(proc_rows) == 7
    for row in proc_rows:
        assert row.is_agent_entry is False
        assert row.parent_workflow is None
        assert row.parent_timestamp is None
        assert row.is_workflow_step_child is False


def _assert_info_header_proc_badge(page: AcePage) -> None:
    info = page.app.query_one("#agent-info-panel", AgentInfoPanel)
    header = info._build_display_text().plain.split(" · group:", 1)[0]

    assert header == "2 agents [1 running · 1 waiting] ⚙7"
    assert header.index("]") < header.index("⚙7")
    assert "procs" not in header
    assert "agents ·" not in header


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "agents_named_procs_120x40"),
        ((90, 30), "agents_named_procs_90x30"),
    ],
)
async def test_agents_named_proc_list_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, PROC_TURN_VISUAL_NOW)
    patch_named_proc_project_names(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=named_proc_visual_agents())

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
            title="ACE agents stand-alone named procs",
        )


async def test_agents_named_proc_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, PROC_TURN_VISUAL_NOW)
    patch_named_proc_project_names(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=named_proc_visual_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _seeded_agents_tab(page)

        label = "Scoped verification for the typed launch matrix"
        page.app.current_idx = _named_proc_index(page, label)
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        assert detail._current_agent is not None
        assert detail._current_agent.is_named_proc
        rendered = prompt_header_and_body_text(prompt)
        assert "NAMED PROC" in rendered
        assert "COMMAND" in rendered
        assert "SAFE PREVIEW" not in rendered
        assert rendered.index("COMMAND") < rendered.index("PROC DETAILS")
        assert "just check" in rendered

        # Zoom the focused deck in place so the golden shows the complete
        # named-proc detail composition.
        await page.press("Z")
        await page.expect_no_modal()
        await wait_for_visual_idle(page)
        assert detail.is_deck_zoomed is True
        assert_page_svg_contains(page, "NAMED PROC")

        ace_png_visual.assert_page_png(
            page,
            "agents_named_proc_detail_120x40",
            title="ACE agents named-proc detail",
        )
