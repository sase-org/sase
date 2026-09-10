"""ACE PNG visual snapshots for the `=alias` model-alias shortcut completion.

Pins how ``PromptInputBar`` renders the ``=alias`` shortcut panel: full menu in
both themes, filtered preview, narrow-width wrapping, and the stacked-pane
layout. Provider and model values are fixed fakes (as the Models-panel
fixtures do) so the goldens never depend on installed provider CLIs. Goldens
live in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from tests.ace.tui.visual._ace_model_completion_png_snapshot_fixtures import (
    ALIAS_ROWS,
    LONG_ALIAS_ROWS,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import TWO_PANE_PROMPT
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_model_alias_completion_full_dark_120x40",
            "ACE prompt input — equals alias completion full menu, dark theme",
        ),
        (
            "textual-light",
            "prompt_model_alias_completion_full_light_120x40",
            "ACE prompt input — equals alias completion full menu, light theme",
        ),
    ],
)
async def test_model_alias_completion_full_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "=")

        bar.show_file_completions(
            "",
            ALIAS_ROWS,
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="equals alias completion full-menu visibility",
        )
        await wait_for_svg_contains(page, "Enter → %m:@large")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_model_alias_completion_filtered_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Route =sc")

        bar.show_file_completions(
            "sc",
            [ALIAS_ROWS[3]],
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "@scout")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_filtered_light_120x40",
            title="ACE prompt input — filtered equals alias completion, light theme",
        )


async def test_model_alias_completion_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Explain =observability")

        bar.show_file_completions(
            "observability",
            LONG_ALIAS_ROWS,
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:@observability")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_narrow_70x24",
            title="ACE prompt input — narrow equals alias completion",
        )


async def test_model_alias_completion_stacked_pane_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        bar.show_file_completions(
            "la",
            [ALIAS_ROWS[0]],
            selected_index=0,
            completion_kind=MODEL_ALIAS_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:@large")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_alias_completion_stack_light_120x40",
            title="ACE prompt stack — equals alias completion, light theme",
        )
