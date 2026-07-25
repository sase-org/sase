"""ACE PNG visual snapshot for the ``+`` project completion menu (sase-4z.2).

Pins how ``PromptInputBar`` renders the ``vcs_project`` completion panel: the
``projects`` border title and one row per enabled project showing the project
name in an accent color, its provider, the resulting ``#gh:sase`` tag dimmed as
the expansion hint, and the description. The bar is mounted over the running app
so the full ``styles.tcss`` applies exactly as at runtime. Goldens live in
``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.xprompt.vcs_project_completion import VcsProjectEntry
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _vcs_candidate(
    name: str,
    *,
    vcs: str,
    provider: str,
    description: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=name,
        insertion=f"#{vcs}:{name}",
        is_dir=False,
        name=name,
        metadata=VcsProjectEntry(
            name=name,
            vcs_prefix=vcs,
            display_tag=f"#{vcs}:{name}",
            provider_display=provider,
            description=description,
        ),
    )


_VCS_PROJECT_ROWS = [
    _vcs_candidate(
        "sase",
        vcs="gh",
        provider="GitHub",
        description="Structured agentic software engineering",
    ),
    _vcs_candidate(
        "sase-core",
        vcs="gh",
        provider="GitHub",
        description="Shared Rust core backend",
    ),
    _vcs_candidate(
        "dotfiles",
        vcs="git",
        provider="Git",
        description="Personal chezmoi configuration",
    ),
]


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="VCS project prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_vcs_project_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, "Describe this repo. +")

        # Render the project menu deterministically (the on-disk catalog is not
        # available in the snapshot harness).
        bar.show_file_completions(
            "",
            _VCS_PROJECT_ROWS,
            selected_index=0,
            completion_kind=VCS_PROJECT_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="VCS project completion visibility",
        )
        await wait_for_svg_contains(page, "sase-core")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_project_completion_panel_120x40",
            title="ACE prompt input — + project completion menu",
        )
