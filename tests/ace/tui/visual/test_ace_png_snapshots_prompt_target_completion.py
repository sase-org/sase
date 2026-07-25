"""ACE PNG snapshots for kind-aware wait and fork target completion."""

from __future__ import annotations

from typing import Literal

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    AgentVcsWorkflow,
)
from sase.ace.tui.widgets.directive_completion import DirectiveArgCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
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


def _target(
    name: str,
    *,
    kind: Literal["agent", "family", "clan", "tribe"],
    status: str,
    members: tuple[str, ...] = (),
) -> CompletionCandidate:
    workflow = (
        AgentVcsWorkflow(
            tag="#gh:sase",
            workflow_type="gh",
            project="sase",
            provider_display="GitHub",
            style="bold #5FD7FF",
        )
        if kind == "agent"
        else None
    )
    metadata = AgentCompletionCandidate(
        name=name,
        label=name,
        status=status,
        kind=kind,
        member_count=len(members) if members else None,
        aggregate_status=status if kind != "agent" else None,
        member_names=members,
        agent_count=2 if kind == "tribe" else None,
        clan_count=1 if kind == "tribe" else None,
        vcs_workflow=workflow,
        prompt_snippet="Polish target completion rows" if kind == "agent" else "",
    )
    return CompletionCandidate(
        display=name,
        insertion=name,
        is_dir=False,
        name=name,
        metadata=metadata,
    )


_TARGET_ROWS = [
    _target(
        "@builders",
        kind="tribe",
        status="RUNNING",
        members=("review.alpha", "review.beta", "ship--code", "coder"),
    ),
    _target(
        "review",
        kind="clan",
        status="WAITING",
        members=("review.alpha", "review.beta"),
    ),
    _target(
        "ship",
        kind="family",
        status="DONE",
        members=("ship--plan", "ship--code"),
    ),
    _target("coder", kind="agent", status="RUNNING"),
]


def _wait_keyword(value: str, description: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=value,
        insertion=value,
        is_dir=False,
        name=value.removesuffix("="),
        metadata=DirectiveArgCompletionMetadata(
            directive_name="wait",
            description=description,
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
        description="target-completion prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_wait_target_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, "%wait:")
        bar.show_file_completions(
            "%wait:",
            [
                _wait_keyword(
                    "priority=", "lower values start first; the default is 10"
                ),
                _wait_keyword("runners=", "wait for an available runner"),
                _wait_keyword("time=", "wait until a time floor"),
                *_TARGET_ROWS,
            ],
            selected_index=3,
            completion_kind="directive_arg",
        )
        await wait_for_svg_contains(page, "@builders")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_wait_target_completion_120x40",
            title="ACE prompt input — wait target completion kinds",
        )


async def test_fork_target_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, "#fork:")
        bar.show_file_completions(
            "#fork:",
            _TARGET_ROWS,
            selected_index=1,
            completion_kind="xprompt_arg_agent",
        )
        await wait_for_svg_contains(page, "ship--code")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_fork_target_completion_120x40",
            title="ACE prompt input — fork target completion kinds",
        )
