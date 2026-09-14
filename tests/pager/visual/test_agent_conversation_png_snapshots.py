"""Conversation layout stays readable at wide and narrow pager widths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.testing.wait import wait_for
from sase.ace.tui.actions.agents._metadata_pager_document import (
    build_agent_metadata_document,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailHeaderSummary
from sase.pager.app import SasePager
from sase.pager.screen import PagerScreen
from tests.ace.agent_artifact_startup_fixtures import make_agent
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


class _SvgExport:
    def __init__(self, app: SasePager) -> None:
        self.app = app

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        return self.app.export_screenshot(title=title, simplify=simplify)


@pytest.mark.parametrize("size", [(120, 40), (60, 30)])
async def test_agent_conversation_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    tmp_path: Path,
    size: tuple[int, int],
) -> None:
    agent = make_agent()
    agent.agent_name = "pager-review"
    agent.stop_time = agent.start_time
    agent.artifacts_dir = str(tmp_path)
    (tmp_path / "raw_xprompt.md").write_text(
        "#review Read src/sase/cli_pager.py and explain the result."
    )
    (tmp_path / "run_prompt.md").write_text(
        "## Review the pager\n\n"
        "Keep prompts and replies readable, searchable, and easy to navigate.\n\n"
        "Check the implementation in `src/sase/cli_pager.py`."
    )
    (tmp_path / "live_reply.md").write_text(
        "## Findings\n\n"
        "The metadata document now includes the **complete conversation**.\n\n"
        "- Original xprompt and expanded prompt\n"
        "- Live reply with saved-response fallback\n"
        "- Refresh keeps the current section\n\n"
        "```python\n"
        "sections = metadata + conversation\n"
        "```\n"
    )
    with (
        patch(
            "sase.ace.tui.actions.agents._metadata_pager_document.build_detail_header_summary",
            return_value=DetailHeaderSummary(),
        ),
        patch(
            "sase.ace.tui.actions.agents._metadata_pager_document._content_section",
            return_value=None,  # Keep the ephemeral fixture path out of the golden.
        ),
    ):
        document = build_agent_metadata_document(agent)
    app = SasePager(document)
    async with app.run_test(size=size) as pilot:
        screen = app.screen
        assert isinstance(screen, PagerScreen)
        await wait_for(
            pilot,
            lambda: (
                all(
                    s.identity in screen._syntax_attempted
                    for s in document.sections[-3:]
                )
                and not screen._syntax_pass_running
            ),
        )
        xprompt_index = next(
            i
            for i, section in enumerate(document.sections)
            if section.title == "AGENT XPROMPT"
        )
        await pilot.press(*(["ctrl+n"] * xprompt_index))
        await pilot.pause()
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            f"agent_conversation_{size[0]}x{size[1]}",
            title="Agent conversation",
        )
