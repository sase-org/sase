"""ACE TUI PNG visual snapshot coverage for Agents-tab linked repos."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from sase.ace.changespec.models import DeltaEntry
from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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


def _linked_repo_diff_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-linked-diff",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 6, 23, 15, 30, 0),
        raw_suffix="20260623-153000-linked-diff",
        agent_name="linked.repo.diff",
        llm_provider="codex",
        model="gpt-5",
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/workspace/sase-core_14",
                workspace_strategy="suffix",
            ),
        ),
    )


def _linked_repo_commits_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-commits",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 6, 23, 16, 0, 0),
        stop_time=datetime(2026, 6, 23, 16, 8, 30),
        raw_suffix="20260623-160000-linked-commits",
        agent_name="commits",
        llm_provider="codex",
        model="gpt-5",
        step_output={
            "meta_commit_message": (
                "feat: linked core commit\n\n"
                "Attribute persisted commit metadata to the linked workspace."
            ),
            "meta_new_commit": "9f8e7d6c5b4a3",
            "meta_commit_cwd": "/workspace/sase-core_18",
        },
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/workspace/sase-core_18",
                workspace_strategy="suffix",
            ),
            LinkedRepoMetadata(
                name="sase-github",
                workspace_dir="/workspace/sase-github_18",
                workspace_strategy="suffix",
            ),
        ),
    )


def _seed_linked_repo_visual_delta(
    monkeypatch: pytest.MonkeyPatch,
    agent: Agent,
) -> None:
    diff_text = "\n".join(
        [
            "diff --git a/crates/core/src/lib.rs b/crates/core/src/lib.rs",
            "index 1234567..89abcde 100644",
            "--- a/crates/core/src/lib.rs",
            "+++ b/crates/core/src/lib.rs",
            "@@ -1,5 +1,8 @@",
            " pub fn build_summary() -> Summary {",
            "-    Summary::default()",
            "+    let mut summary = Summary::default();",
            "+    summary.enable_linked_repo_pages = true;",
            "+    summary",
            " }",
            "",
            "+pub fn linked_repo_panel_label() -> &'static str {",
            '+    "sase-core"',
            "+}",
        ]
    )
    monkeypatch.setitem(
        linked_deltas_mod._selected_agent_linked_delta_cache,
        agent.identity,
        (
            LinkedDeltaGroup(
                repo_name="sase-core",
                workspace_dir="/workspace/sase-core_14",
                entries=(
                    DeltaEntry(
                        path="crates/core/src/lib.rs",
                        change_type="M",
                    ),
                ),
                diff_text=diff_text,
                fetched_at=datetime(2026, 6, 23, 15, 31, 42),
            ),
        ),
    )
    monkeypatch.setitem(
        linked_deltas_mod._selected_agent_cache_monotonic,
        agent.identity,
        time.monotonic() + 3600.0,
    )


async def test_agents_linked_repo_diff_file_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _linked_repo_diff_agent()
    _seed_linked_repo_visual_delta(monkeypatch, agent)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sase-core")
        assert_page_svg_contains(page, "linked repo")
        assert_page_svg_contains(page, "/workspace/sase-core_14")
        ace_png_visual.assert_page_png(
            page,
            "agents_linked_repo_diff_file_panel_120x40",
            title="ACE agents linked repo diff file panel",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_agents_commit_messages_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _linked_repo_commits_agent()
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "COMMITS:")
        assert_page_svg_contains(page, "feat: linked core")
        assert_page_svg_contains(page, "9f8e7d6c5b4a")
        assert_page_svg_contains(page, "sase-core")
        ace_png_visual.assert_page_png(
            page,
            "agents_commit_messages_panel_120x40",
            title="ACE agents commit messages panel",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
