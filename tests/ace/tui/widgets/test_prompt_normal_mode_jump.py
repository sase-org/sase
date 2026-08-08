"""NORMAL-mode ``Ctrl+]`` jump-to-definition keymap tests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.graphics import ArtifactFileViewerResult
from sase.ace.tui.modals.jump_action_modal import JumpActionModal
from sase.ace.tui.widgets._prompt_jump_target import (
    JumpError,
    JumpTarget,
    JumpToken,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry


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


def _skill_entry(name: str = "sase_plan") -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=f"skills/{name}",
        skill_name=name,
        insertion=f"#skills/{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
        is_skill=True,
    )


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


async def test_ctrl_bracket_on_warm_slash_skill_uses_skill_and_prompt_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = JumpTarget(
        kind_label="skill",
        icon="/",
        title="/sase_plan",
        source_path="/workspace/skills/sase_plan.md",
        line=4,
        col=1,
        loadable_markdown="Plan body\n",
    )
    seen: list[tuple[JumpToken, str | None, str]] = []

    def fake_resolve(
        token: JumpToken,
        *,
        project: str | None,
        base_dir: str,
    ) -> JumpTarget:
        seen.append((token, project, base_dir))
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: True
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fake_resolve,
    )

    async with PromptPage("use /sase_plan", cursor=(0, 6), size=(80, 24)) as page:
        page.ta.app._prompt_context = SimpleNamespace(
            project_name="sase",
            workspace_dir="/workspace/sase",
            is_home_mode=False,
        )
        page.ta._xprompt_arg_assist_entries_by_project["sase"] = [_skill_entry()]

        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: _top_is_jump_modal(page))

        token, project, base_dir = seen[0]
        assert token.raw == "/sase_plan"
        assert token.target == "sase_plan"
        assert token.reference_prefix == "/"
        assert project == "sase"
        assert base_dir == "/workspace/sase"


async def test_ctrl_bracket_on_cold_slash_candidate_defers_without_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[str | None] = []

    def fail_resolve(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cold slash candidate must defer resolution")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        fail_resolve,
    )

    async with PromptPage("/sase_plan", cursor=(0, 1), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "_schedule_xprompt_assist_warm",
            warmed.append,
        )

        await page.press("ctrl+right_square_bracket")
        await page.pause()

        assert warmed == [None]
        assert page.ta._prompt_jump_request_id == 0
        assert not _top_is_jump_modal(page)


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


async def test_ctrl_bracket_on_image_views_it_inside_suspend_without_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "prompt-preview.PNG"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    viewer_calls: list[str] = []
    refocus_calls: list[None] = []
    suspended = False

    @contextmanager
    def fake_suspend():
        nonlocal suspended
        suspended = True
        try:
            yield
        finally:
            suspended = False

    def fake_viewer(path: str) -> ArtifactFileViewerResult:
        assert suspended is True
        viewer_calls.append(path)
        return ArtifactFileViewerResult(True)

    def fail_editor(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("image jump must not use an editor-backed action")

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session", lambda: True
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.view_artifact_file",
        fake_viewer,
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_open_jump_target_in_this_pane",
        fail_editor,
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_open_jump_target_in_tmux_pane_async",
        fail_editor,
    )

    prompt = f"open {image}"
    async with PromptPage(prompt, cursor=(0, 5), size=(80, 24)) as page:
        monkeypatch.setattr(page.ta.app, "suspend", fake_suspend)
        monkeypatch.setattr(
            page.ta,
            "_refocus_if_needed",
            lambda: refocus_calls.append(None),
        )

        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: viewer_calls == [str(image)])

        assert suspended is False
        assert refocus_calls == [None]
        assert not _top_is_jump_modal(page)


async def test_ctrl_bracket_on_image_surfaces_viewer_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "prompt-preview.webp"
    image.write_bytes(b"image")
    notifications: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.view_artifact_file",
        lambda _path: ArtifactFileViewerResult(
            False,
            warning="kitten is required to display images",
        ),
    )

    prompt = f"view {image}"
    async with PromptPage(prompt, cursor=(0, 5), size=(80, 24)) as page:
        monkeypatch.setattr(page.ta.app, "suspend", nullcontext)
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: bool(notifications))

        assert notifications == [("kitten is required to display images", "warning")]


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
