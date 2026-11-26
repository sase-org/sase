"""PNG snapshot coverage for the question copy panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _spotlight_questions() -> list[dict[str, object]]:
    return [
        {
            "header": "Mac GUI",
            "question": (
                "Mac busy-process fixes are measured and recorded. Spotlight: "
                "System Settings → Spotlight → Search Privacy → + → paste each "
                "folder. Chrome: open chrome://settings/performance. "
                "Run `launchctl kickstart -k gui/501/com.apple/Spotlight`, "
                "then read plan:202611/mac_busy_process_fixes.md. What did you do?"
            ),
            "options": [
                {
                    "label": "Done, both",
                    "description": "Added all 7 Spotlight folders and toggled Memory Saver",
                },
                {"label": "Skip for now"},
            ],
            "copy": [
                {"label": ".sase", "text": "/Users/bbugyi/.sase"},
                {
                    "label": "App Support/sase",
                    "text": "/Users/bbugyi/Library/Application Support/sase",
                },
                {"text": "/Users/bbugyi/.cargo"},
                {"text": "/Users/bbugyi/.rustup"},
                {
                    "label": "bob-cli/target",
                    "text": "/Users/bbugyi/projects/github/bobs-org/bob-cli/target",
                },
                {
                    "label": "sase-core/target",
                    "text": "/Users/bbugyi/projects/github/sase-org/sase-core/target",
                },
                {
                    "label": "mac-capture/.build",
                    "text": "/Users/bbugyi/projects/github/bobs-org/bob-mac-capture/.build",
                },
                {
                    "label": "Chrome Memory Saver",
                    "text": "chrome://settings/performance",
                },
            ],
        }
    ]


def _copied_bundle(app: object, key: str, texts: list[str]) -> None:
    progress = getattr(app, "_question_copy_progress", None)
    if progress is None:
        progress = {}
        app._question_copy_progress = progress
    progress[key] = set(texts)


async def _open_copy_panel(
    page: AcePage, questions: list[dict[str, object]], bundle_key: str
) -> None:
    page.app.push_screen(UserQuestionModal(questions, copy_bundle_key=bundle_key))
    await page.expect_modal("UserQuestionModal")
    await wait_for_visual_idle(page)
    await page.press("y")
    await page.expect_modal("QuestionCopyModal")
    await wait_for_svg_contains(page, "Copy from question")
    await wait_for_visual_idle(page)


async def test_question_copy_panel_dark_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        questions = _spotlight_questions()
        copies = [str(item["text"]) for item in questions[0]["copy"][:3]]  # type: ignore[index]
        _copied_bundle(page.app, "/visual/bundle", copies)
        await _open_copy_panel(page, questions, "/visual/bundle")

        ace_png_visual.assert_page_png(
            page,
            "question_copy_panel_dark_120x40",
            title="ACE question copy panel — Spotlight fixture, 3 of 8 copied",
        )


async def test_question_copy_panel_light_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(80, 24),
        patches=patches(),
    ) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        questions = _spotlight_questions()
        copies = [str(item["text"]) for item in questions[0]["copy"][:3]]  # type: ignore[index]
        _copied_bundle(page.app, "/visual/bundle", copies)
        await _open_copy_panel(page, questions, "/visual/bundle")

        ace_png_visual.assert_page_png(
            page,
            "question_copy_panel_light_80x24",
            title="ACE question copy panel — narrow light layout",
        )


async def test_question_copy_panel_no_snippets_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_copy_panel(
            page,
            [
                {
                    "header": "Mac GUI",
                    "question": "What did you do?",
                    "options": [{"label": "Done"}],
                }
            ],
            "/visual/empty",
        )

        ace_png_visual.assert_page_png(
            page,
            "question_copy_panel_no_snippets_dark_120x40",
            title="ACE question copy panel — no declared snippets",
        )
