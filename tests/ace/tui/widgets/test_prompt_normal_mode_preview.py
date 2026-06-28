"""NORMAL-mode ``K`` preview keymap tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewError,
    PreviewPayload,
    PreviewToken,
)


async def _wait_for(
    page: PromptPage,
    predicate: Callable[[], bool],
    *,
    attempts: int = 20,
) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await page.pause()
    assert predicate()


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], PreviewPanelModal)


async def test_k_on_previewable_token_pushes_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = PreviewPayload(
        kind_label="xprompt",
        icon="#",
        title="#foo",
        source_path="/tmp/foo.md",
        content="# Foo\n\nBody\n",
        lexer="markdown",
    )
    seen: list[tuple[str, str | None, str]] = []

    def fake_resolve(
        token: PreviewToken,
        *,
        project: str | None,
        base_dir: str,
    ) -> object:
        seen.append((token.target, project, base_dir))
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("run #foo", cursor=(0, 5), size=(80, 24)) as page:
        await page.press("K")
        await _wait_for(page, lambda: _top_is_preview(page))

        assert seen and seen[0][0] == "foo"
        assert isinstance(page.ta.app.screen_stack[-1], PreviewPanelModal)


async def test_k_on_non_previewable_text_does_not_resolve_or_push_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_resolve(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("plain text", cursor=(0, 0), size=(80, 24)) as page:
        await page.press("K")
        await page.pause()

        assert called is False
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_k_resolution_error_does_not_push_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(*_args: object, **_kwargs: object) -> object:
        raise PreviewError("No xprompt or skill named '#missing' found")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("#missing", cursor=(0, 1), size=(80, 24)) as page:
        await page.press("K")
        await _wait_for(page, lambda: page.ta._prompt_preview_request_id == 1)
        await page.pause()

        assert not _top_is_preview(page)


async def test_counted_k_is_noop_and_does_not_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_resolve(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("#foo", cursor=(0, 1), size=(80, 24)) as page:
        await page.press("2", "K")
        await page.pause()

        assert called is False
        assert page.ta._prompt_preview_request_id == 0
        assert page.ta._count_prefix == ""
        assert not _top_is_preview(page)


async def test_k_does_not_overwrite_dot_repeat() -> None:
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"

        await page.press("K")
        await page.press(".")

        assert page.text == "three"
