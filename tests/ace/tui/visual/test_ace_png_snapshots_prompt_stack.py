"""ACE TUI PNG visual snapshots for multi-agent prompt stack layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.prompt_submit_choice_modal import PromptSubmitChoiceModal
from sase.ace.tui.widgets import StashedPromptsIndicator
from sase.ace.tui.widgets.prompt_stack import XPromptBinding, XPromptReadonlyTarget
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import (
    COMPACT_PROMPT,
    TWO_PANE_PROMPT,
    XPROMPT_COMPLETION_ROWS,
    mount_prompt_bar,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


TARGETED_MARKDOWN = (
    "---\n"
    "description: Review the changed prompt target flow\n"
    "tags:\n"
    "  - ace\n"
    "  - target\n"
    "---\n"
    "Audit the targeted xprompt editing state and keep the review notes concise."
)


def _write_target_source(
    tmp_path: Path,
    name: str,
    body: str = TARGETED_MARKDOWN,
) -> tuple[Path, Path]:
    fake_home = tmp_path / "home"
    source = fake_home / "sase" / "xprompts" / f"{name}.md"
    source.parent.mkdir(parents=True)
    source.write_text(body, encoding="utf-8")
    return source, fake_home


async def test_prompt_stack_two_panes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, TWO_PANE_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_two_panes_120x40",
            title="ACE prompt stack — active lower pane",
        )


async def test_prompt_stack_active_upper_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        # Focus the top pane so the accent border moves up and the bottom pane
        # dims — the mirror image of the default active-lower snapshot.
        bar.focus_item(0)
        await wait_for_state(
            page,
            lambda: bar._stack.selected_index == 0 and bar.active_text_area().has_focus,
            description="upper prompt pane focus",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_active_upper_120x40",
            title="ACE prompt stack — active upper pane",
        )


async def test_prompt_submit_choice_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, TWO_PANE_PROMPT)

        page.app.push_screen(PromptSubmitChoiceModal(prompt_count=2))
        await page.expect_modal("PromptSubmitChoiceModal")
        await wait_for_svg_contains(page, "Launch all 2 prompts")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_submit_choice_modal_120x40",
            title="ACE prompt stack — submit chooser",
        )


async def test_prompt_stack_targeted_clean_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    source, fake_home = _write_target_source(tmp_path, "visual-clean")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "placeholder")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        bar.load_stack_from_xprompt_markdown(
            TARGETED_MARKDOWN,
            binding=XPromptBinding.for_file(source, reference="#visual-clean"),
        )
        await wait_for_svg_contains(page, "#visual-clean")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_targeted_clean_120x40",
            title="ACE prompt stack — targeted clean",
        )


async def test_prompt_stack_targeted_dirty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    source, fake_home = _write_target_source(tmp_path, "visual-dirty")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "placeholder")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        bar.load_stack_from_xprompt_markdown(
            TARGETED_MARKDOWN,
            binding=XPromptBinding.for_file(source, reference="#visual-dirty"),
        )
        bar.active_text_area().text = (
            "Audit the targeted xprompt editing state, then add the dirty note."
        )
        bar._sync_state_from_widgets()
        bar._refresh_title()
        await wait_for_svg_contains(page, "#visual-dirty")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_targeted_dirty_120x40",
            title="ACE prompt stack — targeted dirty",
        )


async def test_prompt_stack_targeted_readonly_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    source, fake_home = _write_target_source(tmp_path, "visual-readonly")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "placeholder")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        bar.load_stack_from_xprompt_markdown(
            TARGETED_MARKDOWN,
            read_only_target=XPromptReadonlyTarget(
                reference="#visual-readonly",
                path=str(source),
            ),
        )
        await wait_for_svg_contains(page, "read-only")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_targeted_readonly_120x40",
            title="ACE prompt stack — targeted read-only",
        )


async def test_prompt_submit_choice_targeted_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    source, fake_home = _write_target_source(tmp_path, "visual-menu")

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, "Review the targeted submit menu.")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        binding = XPromptBinding.for_file(source, reference="#visual-menu")

        page.app.push_screen(
            PromptSubmitChoiceModal(
                prompt_count=1,
                target=binding,
                is_dirty=True,
            )
        )
        await page.expect_modal("PromptSubmitChoiceModal")
        await wait_for_svg_contains(page, "Save to")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_submit_choice_targeted_120x40",
            title="ACE prompt stack — targeted submit chooser",
        )


async def test_prompt_stack_compact_inactive_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 30)) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, COMPACT_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_compact_inactive_80x30",
            title="ACE prompt stack — compact inactive panes",
        )


async def test_prompt_stack_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        # The completion panel is scoped to the active pane; render a
        # deterministic xprompt completion to pin its in-stack styling.
        bar.show_file_completions(
            "fo",
            XPROMPT_COMPLETION_ROWS,
            selected_index=1,
            completion_kind="xprompt",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="xprompt completion panel visibility",
        )
        await wait_for_svg_contains(page, "followup")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_completion_panel_120x40",
            title="ACE prompt stack — completion panel in active pane",
        )


async def test_prompt_stack_g_prefix_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        indicator = page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        )
        indicator.set_count(2)
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        await page.press("escape", "g")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area._pending_keys == "g"
                and bar._g_prefix_hints_visible
            ),
            description="NORMAL-mode g-prefix hint panel",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_g_prefix_hints_120x40",
            title="ACE prompt stack — g prefix hints",
        )
