"""ACE PNG visual for the VCS ref-root completion menu."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    build_no_known_refs_placeholder,
    vcs_ref_completion_candidates,
)
from sase.workspace_provider import VcsNamespaceEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry
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


_VCS_REF_SOURCE = [
    VcsProjectEntry(
        name="sase",
        vcs_prefix="gh",
        display_tag="#gh:sase",
        provider_display="GitHub",
        description="Structured agentic software engineering",
    ),
    VcsProjectEntry(
        name="ship-completion",
        vcs_prefix="gh",
        display_tag="#gh:ship-completion",
        provider_display="GitHub",
        kind="patch",
        project="sase",
        status="Ready",
    ),
    VcsNamespaceEntry("sase-org", description="2 active projects"),
]

_VCS_REF_SOURCE_NO_ORGS = [
    VcsProjectEntry(
        name="dotfiles",
        vcs_prefix="git",
        display_tag="#git:dotfiles",
        provider_display="Git",
        description="Personal configuration",
    ),
    VcsProjectEntry(
        name="ship-completion",
        vcs_prefix="git",
        display_tag="#git:ship-completion",
        provider_display="Git",
        kind="patch",
        project="sase",
        status="Ready",
    ),
]


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="VCS ref prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_vcs_ref_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#gh:")
        rows, _source_empty, _has_namespaces = vcs_ref_completion_candidates(
            "gh",
            "",
            entries=_VCS_REF_SOURCE,
        )

        bar.show_file_completions(
            "GitHub · projects & PRs & orgs",
            rows,
            selected_index=0,
            completion_kind=VCS_REF_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS ref completion visibility",
        )
        await wait_for_svg_contains(page, "ship-completion")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_ref_completion_panel_120x40",
            title="ACE prompt input - VCS ref completion menu",
        )


async def test_vcs_ref_completion_panel_no_orgs_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#git:")
        rows, _source_empty, _has_namespaces = vcs_ref_completion_candidates(
            "git",
            "",
            entries=_VCS_REF_SOURCE_NO_ORGS,
        )

        bar.show_file_completions(
            "Git · projects & PRs",
            rows,
            selected_index=0,
            completion_kind=VCS_REF_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS ref completion visibility without namespaces",
        )
        await wait_for_svg_contains(page, "dotfiles")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_ref_completion_panel_no_orgs_120x40",
            title="ACE prompt input - VCS ref completion menu without orgs",
        )


async def test_vcs_ref_completion_panel_placeholder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "#git:")

        bar.show_file_completions(
            "Git · projects & PRs",
            [build_no_known_refs_placeholder()],
            selected_index=0,
            completion_kind=VCS_REF_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="empty VCS ref completion visibility",
        )
        await wait_for_svg_contains(page, "no known projects, PRs, or organizations")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_ref_completion_panel_placeholder_120x40",
            title="ACE prompt input - VCS ref completion empty placeholder",
        )
