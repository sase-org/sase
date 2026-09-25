"""sase's TUI PNG visual snapshot coverage for Agents-tab linked repos."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.patch.models import DeltaEntry
from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _display as file_panel_display_mod
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    get_cached_detail_header_summary,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    main_deck_scroll,
    page_svg_text,
    pin_decks_paged,
    reveal_agent_file_view,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_COMMIT_DIFF_DISPLAY_FIXTURES = Path("tests/ace/tui/visual/fixtures/commit_diffs")
_COMMIT_DIFF_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "commit_diffs"
_COMMIT_DELTA_SUMMARY_TIMEOUT_SECONDS = 30.0


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
            ),
        ),
    )


def _linked_repo_commits_agent() -> Agent:
    primary_diff_1 = _COMMIT_DIFF_FIXTURES / "primary_001.diff"
    primary_diff_2 = _COMMIT_DIFF_FIXTURES / "primary_002.diff"
    linked_diff = _COMMIT_DIFF_FIXTURES / "linked_001.diff"
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
        diff_path=str(primary_diff_2),
        workspace_dir="/workspace/sase_18",
        step_output={
            "meta_commit_message": (
                "feat: linked core commit\n\n"
                "Attribute persisted commit metadata to the linked workspace."
            ),
            "meta_new_commit": "9f8e7d6c5b4a3",
            "meta_commit_cwd": "/workspace/sase-core_18",
            "meta_commits": [
                {
                    "message": "feat: primary\n\n"
                    "Persist all commit results for the selected run.",
                    "sha": "1234567890abcdef",
                    "cwd": "/workspace/sase_18/src",
                    "diff_path": str(primary_diff_1),
                },
                {
                    "message": "fix: aggregate deltas\n\n"
                    "Show all primary commit deltas in the metadata panel.",
                    "sha": "abcdef1234567890",
                    "cwd": "/workspace/sase_18/src",
                    "diff_path": str(primary_diff_2),
                },
                {
                    "message": (
                        "feat: linked core commit\n\n"
                        "Attribute persisted commit metadata to the linked workspace."
                    ),
                    "sha": "9f8e7d6c5b4a3",
                    "cwd": "/workspace/sase-core_18",
                    "diff_path": str(linked_diff),
                },
            ],
        },
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/workspace/sase-core_18",
            ),
            LinkedRepoMetadata(
                name="sase-github",
                workspace_dir="/workspace/sase-github_18",
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


def _patch_commit_diff_display_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    original_read_static_file = file_panel_display_mod._read_static_file

    def read_static_file(request_id: int, path: str, mode: str):
        result = original_read_static_file(request_id, path, mode)
        try:
            relative = (
                Path(result.expanded_path).resolve().relative_to(_COMMIT_DIFF_FIXTURES)
            )
        except ValueError:
            return result

        result.expanded_path = str(_COMMIT_DIFF_DISPLAY_FIXTURES / relative)
        return result

    monkeypatch.setattr(file_panel_display_mod, "_read_static_file", read_static_file)


async def _wait_for_commit_delta_summary(page: AcePage, agent: Agent) -> None:
    prompt_panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)

    def _summary_ready() -> bool:
        summary = get_cached_detail_header_summary(prompt_panel, agent)
        return bool(
            summary is not None
            and summary.delta_entries
            and summary.linked_delta_groups
        )

    await wait_for_state(
        page,
        _summary_ready,
        description="linked-repository commit delta summary",
        timeout=_COMMIT_DELTA_SUMMARY_TIMEOUT_SECONDS,
    )
    await wait_for_visual_idle(page)


async def _wait_for_deck_text(page: AcePage, targets: tuple[str, ...]) -> None:
    """Wait until every target is on screen in the focused deck, then settle.

    The deck content loads asynchronously and fits the viewport without
    scrolling, so wait for it instead of pressing scroll keys blindly.
    """
    await wait_for_state(
        page,
        lambda: all(
            target in page_svg_text(page, title="ACE commit deltas deck probe")
            for target in targets
        ),
        description=f"deck text {targets!r}",
    )
    await wait_for_visual_idle(page)


async def test_agents_linked_repo_diff_file_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_decks_paged(monkeypatch)
    agent = _linked_repo_diff_agent()
    _seed_linked_repo_visual_delta(monkeypatch, agent)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await reveal_agent_file_view(page)
        await wait_for_svg_contains(page, "linked repo")

        assert_page_svg_contains(page, "sase-core")
        assert_page_svg_contains(page, "linked repo")
        assert_page_svg_contains(page, "/workspace/sase-core_14")
        # Only the Files deck is shown, so its scroll is the only one to hide.
        main_deck_scroll(page).show_vertical_scrollbar = False
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_linked_repo_diff_file_panel_120x40",
            title="ACE agents linked repo diff file panel",
        )


async def test_agents_commit_messages_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_decks_paged(monkeypatch)
    _patch_commit_diff_display_paths(monkeypatch)
    agent = _linked_repo_commits_agent()
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await _wait_for_commit_delta_summary(page, agent)
        # The commit deltas live in the Main deck and the diff pages in the
        # Files deck; each is captured on its own so file names and diff rows
        # are not wrapped by a half-width split panel.
        await _wait_for_deck_text(
            page, ("Deltas:", "agent_deltas.py", "file_panel.py", "sase-core")
        )
        assert_page_svg_contains(page, "Deltas:")
        assert_page_svg_contains(page, "agent_deltas.py")
        assert_page_svg_contains(page, "file_panel.py")
        assert_page_svg_contains(page, "sase-core")
        # The narrow deck wraps the repo name and sha onto separate rows.
        assert_page_svg_contains(page, "visual_project")
        assert_page_svg_contains(page, "1234567890ab")
        ace_png_visual.assert_page_png(
            page,
            "agents_commit_messages_panel_120x40",
            title="ACE agents commit deltas main deck",
        )

        await reveal_agent_file_view(page)
        await _wait_for_deck_text(page, ("1/3", "primary_001"))
        # The Files deck title carries the page count (the legacy panel's
        # ``files [1/3]`` heading no longer exists).
        assert_page_svg_contains(page, "FILES")
        assert_page_svg_contains(page, "1/3")
        # The narrow deck wraps the fixture path mid-name (``primary_001.d|iff``).
        assert_page_svg_contains(page, "primary_001")
        ace_png_visual.assert_page_png(
            page,
            "agents_commit_messages_files_panel_120x40",
            title="ACE agents commit diff files deck",
        )
