"""ACE PNG snapshots for xprompt keyword-argument completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptArgNameMetadata,
    XPromptInputHint,
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


def _arg_name(
    name: str,
    type_: str,
    position: int,
    *,
    required: bool = True,
    default_display: str | None = None,
    description: str | None = None,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=f"{name}=",
        insertion=f"{name}=",
        is_dir=False,
        name=name,
        metadata=XPromptArgNameMetadata(
            reference_text="#review",
            input_hint=XPromptInputHint(
                name=name,
                type=type_,
                required=required,
                default_display=default_display,
                position=position,
                description=description,
            ),
        ),
    )


_ARG_ROWS = [
    _arg_name("path", "path", 0, description="file to review"),
    _arg_name(
        "enabled",
        "bool",
        1,
        required=False,
        default_display="true",
        description="turn on",
    ),
    _arg_name("count", "int", 2, required=False, default_display="3"),
    _arg_name("label", "str", 3, description="a free-form label"),
]


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        pytest.param(
            "textual-dark",
            "prompt_xprompt_arg_completion_dark_120x40",
            "ACE prompt input — xprompt keyword-argument completion, dark theme",
            id="dark",
        ),
        pytest.param(
            "textual-light",
            "prompt_xprompt_arg_completion_light_120x40",
            "ACE prompt input — xprompt keyword-argument completion, light theme",
            id="light",
        ),
    ],
)
async def test_xprompt_arg_name_completion_png_snapshot(
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
        bar = await mount_prompt_bar(page, "#review(")

        bar.show_file_completions(
            "",
            _ARG_ROWS,
            selected_index=1,
            completion_kind="xprompt_arg_name",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="xprompt argument completion visibility",
        )
        await wait_for_svg_contains(page, "#review args")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
