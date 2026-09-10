"""ACE PNG visual snapshots for enriched `%model` directive completion menus.

Pins how ``PromptInputBar`` renders the four-column ``%model`` grid: concrete
model rows above alias rows, each alias showing its kind badge, resolved
``PROVIDER(model)`` target, and provenance state. Provider and model values are
fixed fakes (as the Models-panel fixtures do) so the goldens never depend on
installed provider CLIs. Goldens live in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_model_completion_png_snapshot_fixtures import (
    ALIAS_ROWS,
    MODEL_ROWS,
    SCOPED_CLAUDE_ROWS,
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
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_model_completion_mixed_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:")

        # A model row is highlighted so the `[@] model aliases` gate hint shows.
        bar.show_file_completions(
            "",
            [*MODEL_ROWS, *ALIAS_ROWS],
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="model completion visibility",
        )
        await wait_for_svg_contains(page, "@small")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_mixed_120x40",
            title="ACE prompt input — %model values with alias rows",
        )


async def test_model_completion_alias_only_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:@")

        # An alias row is highlighted so its description subtitle shows.
        bar.show_file_completions(
            "@",
            ALIAS_ROWS,
            selected_index=3,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="alias-only completion visibility",
        )
        await wait_for_svg_contains(page, "@scout")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_aliases_120x40",
            title="ACE prompt input — %model alias-only menu",
        )


async def test_model_completion_provider_scoped_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "%model:claude/")

        bar.show_file_completions(
            "claude/",
            SCOPED_CLAUDE_ROWS,
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="provider-scoped model completion visibility",
        )
        await wait_for_svg_contains(page, "claude/sonnet")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_completion_provider_scoped_120x40",
            title="ACE prompt input — provider-scoped %model values",
        )
