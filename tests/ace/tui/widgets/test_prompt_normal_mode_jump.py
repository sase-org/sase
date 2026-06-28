"""NORMAL-mode ``Ctrl+]`` jump-to-definition keymap tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.jump_action_modal import JumpActionModal
from sase.ace.tui.widgets._prompt_jump_target import (
    JumpError,
    JumpTarget,
    JumpToken,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


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


def _top_is_jump_modal(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], JumpActionModal)


async def test_ctrl_bracket_on_resolvable_token_pushes_jump_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = JumpTarget(
        kind_label="xprompt",
        icon="#",
        title="#foo",
        source_path="/tmp/foo.md",
        line=4,
        col=1,
        loadable_markdown="Body",
    )
    seen: list[tuple[str, str | None, str]] = []

    def fake_resolve(
        token: JumpToken,
        *,
        project: str | None,
        base_dir: str,
    ) -> JumpTarget:
        seen.append((token.target, project, base_dir))
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: True
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fake_resolve,
    )

    async with PromptPage("run #foo", cursor=(0, 5), size=(80, 24)) as page:
        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: _top_is_jump_modal(page))

        assert seen and seen[0][0] == "foo"
        assert isinstance(page.ta.app.screen_stack[-1], JumpActionModal)


async def test_ctrl_bracket_with_single_action_runs_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = JumpTarget(
        kind_label="file",
        icon="@",
        title="src/main.py",
        source_path="/tmp/main.py",
        line=None,
        col=None,
        loadable_markdown=None,
    )
    calls: list[tuple[str, JumpTarget]] = []

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: False
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        lambda *_args, **_kwargs: payload,
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_perform_jump_action",
        lambda self, choice, target: calls.append((choice, target)),
    )

    async with PromptPage("open src/main.py", cursor=(0, 6), size=(80, 24)) as page:
        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: calls == [("editor", payload)])

        assert not _top_is_jump_modal(page)


async def test_ctrl_bracket_on_plain_text_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False
    notifications: list[tuple[str, str | None]] = []

    def fake_resolve(*_args: object, **_kwargs: object) -> JumpTarget:
        nonlocal called
        called = True
        raise AssertionError("resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fake_resolve,
    )

    async with PromptPage("plain text", cursor=(0, 0), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("ctrl+right_square_bracket")
        await page.pause()

        assert called is False
        assert page.ta._prompt_jump_request_id == 0
        assert notifications == [
            (
                "Move the cursor onto an xprompt, skill, or file path to jump to its definition",
                "warning",
            )
        ]


async def test_ctrl_bracket_resolution_error_toasts_distinct_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str | None]] = []

    def fake_resolve(*_args: object, **_kwargs: object) -> JumpTarget:
        raise JumpError("No xprompt or skill named '#missing' found")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fake_resolve,
    )

    async with PromptPage("#missing", cursor=(0, 1), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: page.ta._prompt_jump_request_id == 1)
        await page.pause()

        assert notifications == [
            ("No xprompt or skill named '#missing' found", "warning")
        ]
        assert not _top_is_jump_modal(page)


async def test_counted_ctrl_bracket_does_not_jump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_resolve(*_args: object, **_kwargs: object) -> JumpTarget:
        nonlocal called
        called = True
        raise AssertionError("resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fake_resolve,
    )

    async with PromptPage("#foo", cursor=(0, 1), size=(80, 24)) as page:
        await page.press("2", "ctrl+right_square_bracket")
        await page.pause()

        assert called is False
        assert page.ta._prompt_jump_request_id == 0
        assert page.ta._count_prefix == ""


async def test_ctrl_bracket_does_not_overwrite_dot_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = JumpTarget(
        kind_label="xprompt",
        icon="#",
        title="#foo",
        source_path="/tmp/foo.md",
        line=1,
        col=1,
        loadable_markdown=None,
    )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: False
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        lambda *_args, **_kwargs: payload,
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_perform_jump_action",
        lambda *_args, **_kwargs: None,
    )

    async with PromptPage("one two #foo three", cursor=(0, 0)) as page:
        await page.press("d", "w")
        assert page.text == "two #foo three"

        page.cursor = (0, 5)
        await page.press("ctrl+right_square_bracket")
        page.cursor = (0, 0)
        await page.press(".")

        assert page.text == "#foo three"
