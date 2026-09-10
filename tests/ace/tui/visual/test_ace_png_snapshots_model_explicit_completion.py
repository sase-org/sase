"""ACE PNG visual snapshots for the `==model` explicit model shortcut completion.

Pins how ``PromptInputBar`` renders the ``==model`` shortcut panel: full menu
in both themes, filtered preview, narrow provider-scoped wrapping, the
stacked-pane layout, advisory badges, and the loading/unavailable status
placeholders. Provider and model values are fixed fakes (as the Models-panel
fixtures do) so the goldens never depend on installed provider CLIs. Goldens
live in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
    build_loading_model_explicit_placeholder,
    build_unavailable_model_explicit_placeholder,
)
from tests.ace.tui.visual._ace_model_completion_png_snapshot_fixtures import (
    ADVISORY_MODEL_ROWS,
    LONG_EXPLICIT_MODEL_ROWS,
    MODEL_ROWS,
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
        pytest.param(
            "textual-dark",
            "prompt_model_explicit_completion_full_dark_120x40",
            "ACE prompt input — double-equals model completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_model_explicit_completion_full_light_120x40",
            "ACE prompt input — double-equals model completion, light theme",
            id="light",
        ),
    ],
)
async def test_model_explicit_completion_full_menu_png_snapshot(
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
        bar = await mount_prompt_bar(page, "==")

        bar.show_file_completions(
            "",
            MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="explicit model shortcut completion visibility",
        )
        await wait_for_svg_contains(page, "Enter → %m:claude-fable-5")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=title,
        )


async def test_model_explicit_completion_filtered_preview_png_snapshot(
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
        bar = await mount_prompt_bar(page, "Route ==fa")

        bar.show_file_completions(
            "fa",
            [MODEL_ROWS[0]],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:claude-fable-5")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_filtered_light_120x40",
            title="ACE prompt input — filtered double-equals model completion",
        )


async def test_model_explicit_completion_narrow_scoped_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "Try ==anthropic/claude")

        bar.show_file_completions(
            "anthropic/claude",
            LONG_EXPLICIT_MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:anthropic/claude")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_scoped_narrow_70x24",
            title="ACE prompt input — narrow provider-scoped double-equals model completion",
        )


async def test_model_explicit_completion_stacked_pane_png_snapshot(
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
            "gp",
            [MODEL_ROWS[2]],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "Enter → %m:gpt-5.6-sol")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_stack_light_120x40",
            title="ACE prompt stack — double-equals model completion, light theme",
        )


async def test_model_explicit_completion_advisory_png_snapshot(
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
        bar = await mount_prompt_bar(page, "==contrib")

        bar.show_file_completions(
            "contrib",
            ADVISORY_MODEL_ROWS,
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "trains on your data")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_model_explicit_completion_advisory_light_120x40",
            title="ACE prompt input — advisory double-equals model completion",
        )


@pytest.mark.parametrize(
    ("candidate", "snapshot_name", "title", "expected"),
    [
        pytest.param(
            build_loading_model_explicit_placeholder(),
            "prompt_model_explicit_completion_loading_120x40",
            "ACE prompt input — loading double-equals model completion",
            "Loading models",
            id="loading",
        ),
        pytest.param(
            build_unavailable_model_explicit_placeholder(),
            "prompt_model_explicit_completion_unavailable_120x40",
            "ACE prompt input — unavailable double-equals model completion",
            "Models unavailable",
            id="unavailable",
        ),
    ],
)
async def test_model_explicit_completion_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    candidate: CompletionCandidate,
    snapshot_name: str,
    title: str,
    expected: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "==")

        bar.show_file_completions(
            "",
            [candidate],
            selected_index=0,
            completion_kind=MODEL_EXPLICIT_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, expected)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
