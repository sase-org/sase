"""ACE PNG snapshots for Jinja2 variable and filter completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.jinja_completion import build_jinja_completion_result
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
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
from tests.ace.tui.widgets._prompt_stack_helpers import mini_xprompt_target

pytestmark = pytest.mark.visual

_STACK_INPUTS = [
    InputArg(
        name="topic",
        type=InputType.LINE,
        description="what to work on",
    ),
    InputArg(
        name="count",
        type=InputType.INT,
        default=3,
        description="how many items",
    ),
]


def _show_engine_menu(
    bar, text: str, selected_index: int, *, mini_scope: bool = False
) -> None:
    """Build the engine menu for *text* and show it on *bar*.

    With *mini_scope* the active pane becomes a mini-xprompt pane, so the
    menu runs in ``xprompt`` scope with the pane's own frontmatter: the
    grid then shows inputs, sase names, conditional rows, Jinja globals,
    and legacy aliases together, with the ``#name`` scope label.
    """
    raw = PromptFrontmatter(inputs=list(_STACK_INPUTS)).serialize()
    if mini_scope:
        bar._stack.selected_item.mini_xprompt_target = mini_xprompt_target(
            name="review",
            frontmatter=raw,
        )
    else:
        bar._stack.set_frontmatter_model(PromptFrontmatter(inputs=list(_STACK_INPUTS)))
    text_area = bar.active_text_area()
    text_area.load_text(text)
    text_area.cursor_location = (0, len(text))
    scope = bar.jinja_scope_for_text_area(text_area)
    result = build_jinja_completion_result(
        text_area.text,
        text_area._absolute_offset(text_area.cursor_location),
        scope,
        scope_label=bar.jinja_scope_label_for_text_area(text_area),
    )
    assert result is not None and result.candidates
    bar.show_file_completions(
        result.prefix,
        result.candidates,
        selected_index=selected_index,
        completion_kind="jinja",
    )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_jinja_variable_completion_dark_120x40",
            "ACE prompt input — Jinja variable completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_jinja_variable_completion_light_120x40",
            "ACE prompt input — Jinja variable completion, light theme",
            id="light",
        ),
    ],
)
async def test_jinja_variable_completion_png_snapshot(
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
        bar = await mount_prompt_bar(page, "draft ")

        # A mini-xprompt pane runs in ``xprompt`` scope with its own
        # inputs: one grid shows inputs, sase names, the conditional
        # ``n`` row, Jinja globals, and a legacy alias together.
        _show_engine_menu(bar, "{{ n", 0, mini_scope=True)
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="jinja variable completion visibility",
        )
        await wait_for_svg_contains(page, "{{ variables")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_jinja_filter_completion_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-dark"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "draft ")

        _show_engine_menu(bar, "{{ value | ", 0)
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="jinja filter completion visibility",
        )
        await wait_for_svg_contains(page, "| filters")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_jinja_filter_completion_120x40",
            title="ACE prompt input — Jinja filter completion, dark theme",
        )
