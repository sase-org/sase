"""ACE PNG coverage for the collapsed agent-header XPROMPT preview."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_header_panel import AgentHeaderPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_LONG_PROSE_XPROMPT = (
    "Can you help me start rendering the `AGENT XPROMPT` section in the\n"
    "sticky header above the agent data deck panel? Make sure that we\n"
    "provide a good preview (use as much space as is available) of the\n"
    "contents in this section (i.e. of the user's prompt) in this header.\n"
    "\n"
    "Requirements:\n"
    "- keep the existing syntax highlighting\n"
    "- reflow hard-wrapped prose into full-width rows\n"
    "- show how many lines are hidden\n"
    "\n"
    "```python\n"
    "fit = fit_xprompt_preview(text, width=width, max_rows=budget)\n"
    "```\n"
    "\n"
    "Then verify the result with live screenshots at two terminal sizes.\n"
    "Finally, update the docs and the PNG goldens.\n"
    "\n"
    "## Follow-ups\n"
) + "".join(
    f"{index}. Recheck header layout case {index} after the golden refresh.\n"
    for index in range(1, 25)
)

_SHORT_DIRECTIVE_XPROMPT = (
    "+sase\n%auto\n%model:opus\n#pr:my_change\nSummarize the header preview.\n"
)


def _preview_agent(artifacts_dir: Path, *, name: str, raw_xprompt: str) -> Agent:
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text(raw_xprompt, encoding="utf-8")
    (artifacts_dir / "01_prompt.md").write_text(
        "Render the AGENT XPROMPT preview in the sticky header.\n",
        encoding="utf-8",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 16, 15, 30, 0),
        raw_suffix="20260716153000",
        agent_name=f"visual.{name}",
        artifacts_dir=str(artifacts_dir),
    )


@pytest.mark.parametrize(
    ("raw_xprompt", "truncated", "tokens", "snapshot_name", "title"),
    [
        (
            _LONG_PROSE_XPROMPT,
            True,
            ("▎", "¶", "sticky header", "…"),
            "agents_header_preview_truncated_160x50",
            "ACE agents collapsed header xprompt preview, truncated",
        ),
        (
            _SHORT_DIRECTIVE_XPROMPT,
            False,
            ("▎", "%auto", "my_change", "Summarize"),
            "agents_header_preview_fits_160x50",
            "ACE agents collapsed header xprompt preview, fits",
        ),
    ],
    ids=["truncated", "fits"],
)
async def test_agents_header_xprompt_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw_xprompt: str,
    truncated: bool,
    tokens: tuple[str, ...],
    snapshot_name: str,
    title: str,
) -> None:
    agent = _preview_agent(
        tmp_path / "header-preview-artifacts",
        name="header-preview",
        raw_xprompt=raw_xprompt,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches(), size=(160, 50)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        panel = page.app.query_one("#agent-header-panel", AgentHeaderPanel)
        await wait_for_state(
            page,
            lambda: panel.rendered_row_count > 2 and not panel.has_class("hidden"),
            description="collapsed header XPROMPT preview",
        )
        await wait_for_visual_idle(page)

        assert ("lines" in str(panel.border_subtitle)) is truncated

        for token in tokens:
            assert_page_svg_contains(page, token)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
