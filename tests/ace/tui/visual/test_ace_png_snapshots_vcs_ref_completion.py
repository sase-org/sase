"""ACE PNG visual for the VCS ref-root completion menu."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.vcs_ref_completion import (
    VCS_REF_COMPLETION_KIND,
    vcs_ref_completion_candidates,
)
from sase.workspace_provider import VcsNamespaceEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
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
        kind="changespec",
        project="sase",
        status="Ready",
    ),
    VcsNamespaceEntry("sase-org", description="2 active projects"),
]


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_visual_idle(page)
    return bar


async def test_vcs_ref_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
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
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "vcs_ref_completion_panel_120x40",
            title="ACE prompt input - VCS ref completion menu",
        )
