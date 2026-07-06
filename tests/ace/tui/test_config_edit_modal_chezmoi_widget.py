"""Chezmoi write-path widget tests for the Config Center edit modal."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_edit_modal as cem
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.config.edit import (
    AppliedResult,
    ConfigEffectivePreview,
    ConfigWritePlan,
    EditPlanResult,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    _no_chezmoi as _no_chezmoi,
)
from tests.ace.tui._config_edit_modal_widget_helpers import (
    config_edit_view,
    open_config_edit_modal,
)


async def test_chezmoi_write_applies_home_target_not_source(tmp_path: Path) -> None:
    """A chezmoi-backed write runs ``chezmoi apply`` on the home target path.

    Regression: the modal previously handed the chezmoi *source* path to
    ``chezmoi apply``, which rejects it as "not in source state". The apply must
    receive the original home target (``plan.write_plan.file``).
    """
    view, user_file = config_edit_view(tmp_path, {"timezone": "US/Pacific"})
    field = view.fields_by_path["timezone"]
    home_target = str(user_file)
    source_path = str(
        tmp_path / "chezmoi" / "home" / "dot_config" / "sase" / "sase.yml"
    )

    plan = EditPlanResult(
        schema_version=1,
        write_plan=ConfigWritePlan(
            file=home_target,
            layer="user",
            key_path=("timezone",),
            op="set",
            has_value=True,
            new_value="UTC",
        ),
        candidate_config={},
        effective_preview=ConfigEffectivePreview(
            path="timezone",
            has_before=True,
            before="US/Pacific",
            has_after=True,
            after="UTC",
            changed=True,
        ),
        validation=(),
        diagnostics=(),
        target_path=source_path,
        used_chezmoi=True,
        current_text="timezone: US/Pacific\n",
        new_text="timezone: UTC\n",
        text_diff="@@ -1 +1 @@\n-timezone: US/Pacific\n+timezone: UTC\n",
    )
    applied = AppliedResult(
        path=source_path,
        op="set",
        key_path=("timezone",),
        created=False,
        used_chezmoi=True,
    )
    apply_chezmoi_mock = MagicMock(
        return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")
    )

    async with AcePage() as page:
        modal = ConfigEditModal(view, field=field)
        result = await open_config_edit_modal(page, modal)
        with (
            patch.object(cem, "plan_config_edit", return_value=plan),
            patch.object(cem, "apply_config_edit", return_value=applied),
            patch.object(cem, "apply_chezmoi", apply_chezmoi_mock),
        ):
            modal.action_confirm()  # plan
            await page.wait_for(lambda _s: modal._plan is not None)
            modal.action_confirm()  # write
            await page.wait_for(lambda _s: bool(result))

    apply_chezmoi_mock.assert_called_once_with(home_target)
    assert result[0] is not None
