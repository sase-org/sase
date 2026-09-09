"""ACE TUI PNG snapshots for model-picker capacity hints."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.llm_provider.test_usage_hints import (
    _claude_model_specific_low,
)
from tests._usage_view_helpers import usage_provider

pytestmark = pytest.mark.visual


def _providers() -> tuple[dict[str, object], ...]:
    return (
        _claude_model_specific_low(),
        usage_provider(
            "codex",
            attention={"kind": "collection_problem", "provider": "codex"},
            collector_health={"state": "failing", "consecutive_failures": 3},
        ),
    )


async def test_model_picker_usage_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    providers = _providers()
    monkeypatch.setattr(
        "sase.ace.tui.modals.model_picker_rows.cached_usage_peek",
        lambda: (providers, frozenset({"claude", "codex"})),
    )

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelPickerModal())
        await page.expect_modal("ModelPickerModal")
        await page.press("o", "p", "u", "s")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "model_picker_usage_hints_120x40",
            title="ACE model picker with scoped capacity hints",
        )
