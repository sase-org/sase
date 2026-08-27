"""ACE PNG visuals for the VCS repository completion menu."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.vcs_repo_completion import (
    VCS_REPO_COMPLETION_KIND,
    build_loading_placeholder,
    vcs_repo_completion_candidates,
)
from sase.workspace_provider import VcsRepoEntry
from sase.xprompt.vcs_repo_completion import VcsRepoFetchResult
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


_VCS_REPO_RESULT = VcsRepoFetchResult(
    status="ok",
    provider_display="GitHub",
    entries=(
        VcsRepoEntry(
            name="sase",
            ref="bbugyi200/sase",
            description="Structured agentic software engineering",
            pushed_at="2026-07-01T00:00:00Z",
        ),
        VcsRepoEntry(
            name="sase-core",
            ref="bbugyi200/sase-core",
            description="Shared Rust backend",
            visibility="private",
            is_fork=True,
            pushed_at="2026-06-15T00:00:00Z",
        ),
        VcsRepoEntry(
            name="old-lab",
            ref="bbugyi200/old-lab",
            description="Archived experiment",
            is_archived=True,
            pushed_at="2025-01-01T00:00:00Z",
        ),
    ),
)


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="VCS repository prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_vcs_repo_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#gh:bbugyi200/")
        rows, _used_placeholder = vcs_repo_completion_candidates(
            _VCS_REPO_RESULT,
            "",
            "bbugyi200",
        )

        bar.show_file_completions(
            "GitHub · bbugyi200/",
            rows,
            selected_index=0,
            completion_kind=VCS_REPO_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS repository completion visibility",
        )
        await wait_for_svg_contains(page, "sase-core")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_repo_completion_panel_120x40",
            title="ACE prompt input - VCS repo completion menu",
        )


async def test_vcs_repo_loading_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#gh:bbugyi200/")

        bar.show_file_completions(
            "gh · bbugyi200/",
            [build_loading_placeholder("bbugyi200")],
            selected_index=0,
            completion_kind=VCS_REPO_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS repository loading completion visibility",
        )
        await wait_for_svg_contains(page, "fetching bbugyi200/ repositories")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_repo_completion_loading_120x40",
            title="ACE prompt input - VCS repo completion loading",
        )


async def test_vcs_repo_error_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#gh:bbugyi200/")
        rows, _used_placeholder = vcs_repo_completion_candidates(
            VcsRepoFetchResult(
                status="error",
                error_kind="auth",
                message="repo listing failed - run `gh auth login`",
                provider_display="GitHub",
            ),
            "",
            "bbugyi200",
        )

        bar.show_file_completions(
            "GitHub · bbugyi200/",
            rows,
            selected_index=0,
            completion_kind=VCS_REPO_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS repository error completion visibility",
        )
        await wait_for_svg_contains(page, "repo listing failed")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_repo_completion_error_120x40",
            title="ACE prompt input - VCS repo completion error",
        )
