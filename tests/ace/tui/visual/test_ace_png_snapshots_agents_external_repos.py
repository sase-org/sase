"""ACE TUI PNG visual snapshot coverage for Agents-tab external repos."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from sase.ace.changespec.models import DeltaEntry
from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _external_repo_diff_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-external-diff",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 13, 18, 30, 0),
        raw_suffix="20260713-183000-external-diff",
        agent_name="external.repo.diff",
        workspace_dir="/workspace/sase_14",
        llm_provider="codex",
        model="gpt-5",
    )


def _seed_external_repo_visual_delta(
    monkeypatch: pytest.MonkeyPatch,
    agent: Agent,
) -> None:
    diff_text = """diff --git a/src/core.py b/src/core.py
index 1234567..89abcde 100644
--- a/src/core.py
+++ b/src/core.py
@@ -1,2 +1,4 @@
 def parse_options(value):
-    return legacy_parse(value)
+    options = tokenize(value)
+    validate_options(options)
+    return options
"""
    monkeypatch.setitem(
        linked_deltas_mod._selected_agent_linked_delta_cache,
        agent.identity,
        (
            LinkedDeltaGroup(
                repo_name="gh:pallets/click",
                workspace_dir=(
                    "/workspace/sase_14/sase/repos/external/gh/pallets/click"
                ),
                entries=(DeltaEntry(path="src/core.py", change_type="M"),),
                diff_text=diff_text,
                fetched_at=datetime(2026, 7, 13, 18, 31, 42),
                kind="external",
            ),
        ),
    )
    monkeypatch.setitem(
        linked_deltas_mod._selected_agent_cache_monotonic,
        agent.identity,
        time.monotonic() + 3600.0,
    )


async def test_agents_external_repo_diff_file_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _external_repo_diff_agent()
    _seed_external_repo_visual_delta(monkeypatch, agent)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "gh:pallets/click")
        assert_page_svg_contains(page, "external repo")
        assert_page_svg_contains(page, "sase/repos/external")
        ace_png_visual.assert_page_png(
            page,
            "agents_external_repo_diff_file_panel_120x40",
            title="ACE agents external repo diff file panel",
        )
