"""PNG snapshot coverage for the question-pane copy cues."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
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
                "What did you do?"
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


def _multiline_questions() -> list[dict[str, object]]:
    return [
        {
            "header": "Spotlight",
            "question": "The GUI steps take a while; prefer one runnable command. Done?",
            "options": [{"label": "Done"}],
            "copy": [
                {
                    "label": "Reset command",
                    "text": "launchctl kickstart -k gui/501/com.apple.Spotlight\nsudo mdutil -E /",
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


async def _open_question_modal(
    page: AcePage, questions: list[dict[str, object]], bundle_key: str
) -> None:
    page.app.push_screen(UserQuestionModal(questions, copy_bundle_key=bundle_key))
    await page.expect_modal("UserQuestionModal")
    await wait_for_visual_idle(page)


async def test_question_pane_cues_dark_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        questions = _spotlight_questions()
        copies = [str(item["text"]) for item in questions[0]["copy"][:3]]  # type: ignore[index]
        _copied_bundle(page.app, "/visual/cues", copies)
        await _open_question_modal(page, questions, "/visual/cues")

        ace_png_visual.assert_page_png(
            page,
            "question_pane_cues_dark_120x40",
            title="ACE question pane cues — Spotlight fixture, 3 of 8 copied",
        )


async def test_question_pane_cues_light_narrow_png_snapshot(
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
        _copied_bundle(page.app, "/visual/cues", copies)
        await _open_question_modal(page, questions, "/visual/cues")

        ace_png_visual.assert_page_png(
            page,
            "question_pane_cues_light_80x24",
            title="ACE question pane cues — narrow light layout",
        )


async def test_question_pane_cues_multiline_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await _open_question_modal(page, _multiline_questions(), "/visual/cues-multi")

        ace_png_visual.assert_page_png(
            page,
            "question_pane_cues_multiline_dark_120x40",
            title="ACE question pane cues — out-of-prose multi-line command",
        )
