"""ACE TUI PNG visual snapshot coverage for revert confirmation."""

from __future__ import annotations

import pytest

from sase.ace.revert_agent import (
    BulkRevertPreview,
    RepoRevertPlan,
    RevertCommit,
    RevertPreview,
    RevertTarget,
)
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ConfirmRevertAgentModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _commit(
    sha: str,
    subject: str,
    paths: tuple[str, ...] = (),
    *,
    agent_tag: str = "visual.revert",
) -> RevertCommit:
    return RevertCommit(
        sha=sha,
        full_sha=f"{sha}000000000000000000000000000000000000",
        subject=subject,
        agent_tag=agent_tag,
        changed_paths=paths,
    )


def _target(name: str, display_name: str | None = None) -> RevertTarget:
    return RevertTarget(
        agent_name=name,
        display_name=display_name or name,
        workspace_dir="/workspace/sase",
    )


def _single_preview() -> RevertPreview:
    docs = _commit("8f3a91c", "Update linked docs after review")
    github = _commit("36bc251", "Wire GitHub revert intent")
    core = _commit("9ac14fe", "Refresh core workspace metadata")
    blocked = _commit("1bb31aa", "Touch primary checkout")
    return RevertPreview(
        agent_name="visual.revert.linked",
        scope="agent",
        workspace_dir="/workspace/sase",
        commits=(docs, github, core),
        repos=(
            RepoRevertPlan("docs-site", "/workspace/sase-docs", False, (docs,)),
            RepoRevertPlan(
                "sase-github",
                "/workspace/sase-github",
                False,
                (github,),
            ),
            RepoRevertPlan("sase-core", "/workspace/sase-core", False, (core,)),
            RepoRevertPlan(
                "primary",
                "/workspace/sase",
                True,
                (blocked,),
                blocked_reason=(
                    "Workspace has uncommitted changes; commit or discard them first"
                ),
            ),
        ),
    )


def _bulk_preview() -> BulkRevertPreview:
    primary_one = _commit(
        "4aa21f0",
        "Record bulk revert provenance",
        ("sdd/plans/202606/revert_modal_redesign.md", "src/sase/ace/tui.py"),
        agent_tag="visual.bulk.alpha",
    )
    primary_two = _commit(
        "7c51dbe",
        "Tighten marked-agent grouping",
        ("sdd/prompts/202606/revert_modal_redesign.md",),
        agent_tag="visual.bulk.beta",
    )
    linked = _commit(
        "2f98ae1",
        "Sync linked repo revert metadata",
        ("src/sase/ace/revert_agent_models.py",),
        agent_tag="visual.bulk.alpha",
    )
    blocked = _commit(
        "5db032a",
        "Leave dirty visual fixture behind",
        agent_tag="visual.bulk.beta",
    )
    return BulkRevertPreview(
        workspace_dir="/workspace/sase",
        targets=(
            _target("visual.bulk.alpha", "visual bulk alpha"),
            _target("visual.bulk.beta", "visual bulk beta"),
            _target("visual.bulk.idle", "visual bulk idle"),
        ),
        commits=(primary_one, primary_two, linked),
        repos=(
            RepoRevertPlan(
                "primary",
                "/workspace/sase",
                True,
                (primary_one, primary_two),
            ),
            RepoRevertPlan(
                "sase-core",
                "/workspace/sase-core",
                False,
                (linked,),
            ),
            RepoRevertPlan(
                "sase-docs",
                "/workspace/sase-docs",
                False,
                (blocked,),
                blocked_reason="Linked repo workspace has uncommitted changes",
            ),
        ),
        matched_target_names=("visual.bulk.alpha", "visual.bulk.beta"),
        skipped_target_names=("visual.bulk.idle",),
    )


async def test_revert_confirm_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")

        page.app.push_screen(ConfirmRevertAgentModal(_single_preview()))
        await page.expect_modal("ConfirmRevertAgentModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "revert_confirm_modal_single_120x40",
            title="ACE revert confirmation panel",
        )


async def test_revert_confirm_bulk_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")

        page.app.push_screen(ConfirmRevertAgentModal(_bulk_preview()))
        await page.expect_modal("ConfirmRevertAgentModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "revert_confirm_modal_bulk_120x40",
            title="ACE bulk revert confirmation panel",
        )
