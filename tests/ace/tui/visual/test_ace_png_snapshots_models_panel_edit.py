"""ACE TUI PNG visual snapshot for the Models panel's alias edit preview.

Phase 3 (epic sase-5e): pin how :class:`AliasEditPreviewModal` renders the
persistent-edit preview — the operation summary, target file, effective
before→after, and the source-preserving text diff — before the user confirms the
write. The plan is pinned (``plan_alias_edit`` patched) so the diff renders
identically on every run.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel_edit as models_panel_edit
import sase.ace.tui.modals.models_panel_effort_edit as effort_edit
import sase.ace.tui.modals.models_panel_runner_limit_edit as runner_limit_edit
from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.ace.tui.modals.models_panel_effort_edit import (
    DefaultEffortEditPreviewModal,
)
from sase.ace.tui.modals.models_panel_runner_limit_edit import (
    RunnerLimitEditPreviewModal,
)
from sase.config import ConfigEditOp
from sase.config.edit import ConfigEffectivePreview, ConfigWritePlan, EditPlanResult
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


_TARGET = "/home/user/.config/sase/sase.yml"
_DIFF = (
    f"--- a/{_TARGET}\n"
    f"+++ b/{_TARGET}\n"
    "@@ -1,4 +1,4 @@\n"
    " llm_provider:\n"
    "   model_aliases:\n"
    "     builtin:\n"
    '-      medium_worker: "@default"\n'
    "+      medium_worker: claude/opus\n"
    "       small_worker: codex/o3\n"
)

_EFFORT_TARGET = "/home/user/.local/share/chezmoi/home/dot_config/sase/sase.yml"
_EFFORT_DIFF = (
    f"--- a/{_EFFORT_TARGET}\n"
    f"+++ b/{_EFFORT_TARGET}\n"
    "@@ -1,3 +1,3 @@\n"
    " llm_provider:\n"
    "-  default_effort: high\n"
    "+  default_effort: xhigh\n"
    "   provider: claude\n"
)

_RUNNER_LIMIT_TARGET = "/home/user/.local/share/chezmoi/home/dot_config/sase/sase.yml"
_RUNNER_LIMIT_DIFF = (
    f"--- a/{_RUNNER_LIMIT_TARGET}\n"
    f"+++ b/{_RUNNER_LIMIT_TARGET}\n"
    "@@ -1,3 +1,3 @@\n"
    " # global capacity\n"
    "-max_running_agents: 10\n"
    "+max_running_agents: 4\n"
    " llm_provider: {}\n"
)


def _edit_plan() -> EditPlanResult:
    return EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file=_TARGET,
            layer="user",
            key_path=(
                "llm_provider",
                "model_aliases",
                "builtin",
                "medium_worker",
            ),
            op="set",
            has_value=True,
            new_value="claude/opus",
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="llm_provider.model_aliases.builtin.medium_worker",
            has_before=True,
            before="@default",
            has_after=True,
            after="claude/opus",
            changed=True,
        ),
        validation=(),
        diagnostics=(),
        target_path=_TARGET,
        used_chezmoi=False,
        current_text="",
        new_text="",
        text_diff=_DIFF,
    )


def _effort_edit_plan() -> EditPlanResult:
    return EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file="/home/user/.config/sase/sase.yml",
            layer="user",
            key_path=("llm_provider", "default_effort"),
            op="set",
            has_value=True,
            new_value="xhigh",
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="llm_provider.default_effort",
            has_before=True,
            before="high",
            has_after=True,
            after="xhigh",
            changed=True,
        ),
        validation=(),
        diagnostics=(),
        target_path=_EFFORT_TARGET,
        used_chezmoi=True,
        current_text="",
        new_text="",
        text_diff=_EFFORT_DIFF,
    )


def _runner_limit_edit_plan() -> EditPlanResult:
    return EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file="/home/user/.config/sase/sase.yml",
            layer="user",
            key_path=("max_running_agents",),
            op="set",
            has_value=True,
            new_value=4,
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="max_running_agents",
            has_before=True,
            before=10,
            has_after=True,
            after=4,
            changed=True,
        ),
        validation=(),
        diagnostics=(),
        target_path=_RUNNER_LIMIT_TARGET,
        used_chezmoi=True,
        current_text="",
        new_text="",
        text_diff=_RUNNER_LIMIT_DIFF,
    )


async def test_models_panel_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _edit_plan()
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")

        modal = AliasEditPreviewModal(
            "medium_worker", ConfigEditOp.set_value("claude/opus")
        )
        page.app.push_screen(modal)
        await page.expect_modal("AliasEditPreviewModal")
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_edit_preview_120x40",
            title="ACE models panel — alias edit preview (diff + confirm)",
        )


async def test_models_panel_default_effort_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        effort_edit,
        "_plan_default_effort_edit",
        lambda *a, **k: _effort_edit_plan(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")

        modal = DefaultEffortEditPreviewModal("xhigh", override_active=True)
        page.app.push_screen(modal)
        await page.expect_modal("DefaultEffortEditPreviewModal")
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_edit_preview_120x40",
            title="ACE models panel — chezmoi default-effort edit preview",
        )


async def test_models_panel_runner_limit_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        runner_limit_edit,
        "_plan_runner_limit_edit",
        lambda *a, **k: _runner_limit_edit_plan(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")

        modal = RunnerLimitEditPreviewModal(4, override_active=True)
        page.app.push_screen(modal)
        await page.expect_modal("RunnerLimitEditPreviewModal")
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_edit_preview_120x40",
            title="ACE models panel — chezmoi runner-limit edit preview",
        )
