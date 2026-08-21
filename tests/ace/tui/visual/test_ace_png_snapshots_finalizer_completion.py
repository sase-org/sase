"""ACE PNG visual snapshots for the ``%final`` completion menu (sase-s0.2).

Pins how ``PromptInputBar`` renders the aligned selector / policy / provider
grid for required, default, optional, remove, and clear rows. Catalog values
are fixed fixtures so the goldens never depend on the user's installed
providers or config. Goldens live in ``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.directive_completion import FinalizerCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _row(
    value: str,
    *,
    kind: str = "finalizer",
    status: str = "optional",
    provider: str = "",
    documentation: str = "",
) -> CompletionCandidate:
    return CompletionCandidate(
        display=value,
        insertion=value,
        is_dir=False,
        name=value,
        metadata=FinalizerCompletionMetadata(
            value=value,
            kind=kind,
            status=status,
            provider=provider,
            documentation=documentation,
        ),
    )


_FINALIZER_ROWS = [
    _row(
        "commit",
        status="required",
        provider="builtin@commit",
        documentation="Required for this launch.",
    ),
    _row(
        "lint",
        status="default",
        provider="builtin@command",
        documentation="Selected by default.",
    ),
    _row(
        "zoom",
        status="optional",
        provider="plugin@zoom",
        documentation="Optional.",
    ),
    _row(
        "!lint",
        kind="finalizer_remove",
        status="default",
        provider="builtin@command",
        documentation="Remove lint from the launch selection.",
    ),
    _row(
        "none",
        kind="finalizer_clear",
        status="clear",
        documentation="Clear the configured finalizer selection for this launch",
    ),
]


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="finalizer-completion prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_finalizer_completion_mixed_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "%final:")

        bar.show_file_completions(
            "",
            _FINALIZER_ROWS,
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="finalizer completion visibility",
        )
        await wait_for_svg_contains(page, "commit")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_finalizer_completion_mixed_120x40",
            title="ACE prompt input — %final required/default/optional/remove/clear",
        )


async def test_finalizer_completion_mixed_menu_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(70, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "%final:")

        bar.show_file_completions(
            "",
            _FINALIZER_ROWS,
            selected_index=0,
            completion_kind="directive_arg",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="narrow finalizer completion visibility",
        )
        await wait_for_svg_contains(page, "commit")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_finalizer_completion_mixed_70x24",
            title="ACE prompt input — narrow %final completion grid",
        )
