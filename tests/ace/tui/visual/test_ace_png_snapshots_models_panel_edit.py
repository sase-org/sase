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
from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_edit import AliasEditPreviewModal
from sase.config import ConfigEditOp
from sase.config.edit import ConfigEffectivePreview, ConfigWritePlan, EditPlanResult
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
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
    '-      coder: "@default"\n'
    "+      coder: claude/opus\n"
    "       medium_phase_worker: codex/o3\n"
)


def _edit_plan() -> EditPlanResult:
    return EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file=_TARGET,
            layer="user",
            key_path=("llm_provider", "model_aliases", "builtin", "coder"),
            op="set",
            has_value=True,
            new_value="claude/opus",
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="llm_provider.model_aliases.builtin.coder",
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


async def test_models_panel_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel_edit, "plan_alias_edit", lambda *a, **k: _edit_plan()
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        modal = AliasEditPreviewModal("coder", ConfigEditOp.set_value("claude/opus"))
        page.app.push_screen(modal)
        await page.expect_modal("AliasEditPreviewModal")
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_edit_preview_120x40",
            title="ACE models panel — alias edit preview (diff + confirm)",
        )
