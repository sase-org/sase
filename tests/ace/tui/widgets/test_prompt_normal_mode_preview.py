"""NORMAL-mode ``K`` preview keymap tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewError,
    PreviewPayload,
    PreviewToken,
)
from sase.ace.tui.widgets.xprompt_arg_assist import XPromptAssistEntry
from sase.core.word_lookup import DefinitionResult, SpellCheckResult


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], PreviewPanelModal)


def _skill_entry(name: str = "sase_plan") -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=f"skill/{name}",
        skill_name=name,
        insertion=f"#skill/{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
        is_skill=True,
    )


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
        await page.wait_for(lambda: _top_is_preview(page))

        assert seen and seen[0][0] == "foo"
        assert isinstance(page.ta.app.screen_stack[-1], PreviewPanelModal)


async def test_k_on_warm_slash_skill_uses_skill_and_prompt_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = PreviewPayload(
        kind_label="skill",
        icon="/",
        title="/sase_plan",
        source_path="/workspace/sase/sase/skills/sase_plan.md",
        content="Plan body\n",
        lexer="markdown",
    )
    seen: list[tuple[PreviewToken, str | None, str]] = []

    def fake_resolve(
        token: PreviewToken,
        *,
        project: str | None,
        base_dir: str,
    ) -> PreviewPayload:
        seen.append((token, project, base_dir))
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("use /sase_plan", cursor=(0, 6), size=(80, 24)) as page:
        page.ta.app._prompt_context = SimpleNamespace(
            project_name="sase",
            workspace_dir="/workspace/sase",
            is_home_mode=False,
        )
        page.ta._xprompt_arg_assist_entries_by_project["sase"] = [_skill_entry()]

        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))

        token, project, base_dir = seen[0]
        assert token.raw == "/sase_plan"
        assert token.target == "sase_plan"
        assert token.reference_prefix == "/"
        assert project == "sase"
        assert base_dir == "/workspace/sase"


async def test_k_on_cold_slash_candidate_warms_without_sync_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[str | None] = []
    notifications: list[tuple[str, str | None]] = []

    def fail_sync_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("catalog must not build on the keypress path")

    def fail_resolve(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cold slash candidate must defer resolution")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
        fail_sync_build,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fail_resolve,
    )

    async with PromptPage("/sase_plan", cursor=(0, 1), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "_schedule_xprompt_assist_warm",
            warmed.append,
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await page.pause()

        assert warmed == [None]
        assert notifications == [
            ("Skill catalog is still loading; try again", "warning")
        ]
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_k_on_cold_unambiguous_absolute_path_stays_a_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = PreviewPayload(
        kind_label="file",
        icon="@",
        title="/tmp/readme.md",
        source_path="/tmp/readme.md",
        content="Body\n",
        lexer="markdown",
    )
    seen: list[PreviewToken] = []
    warmed: list[str | None] = []

    def fake_resolve(token: PreviewToken, **_kwargs: object) -> PreviewPayload:
        seen.append(token)
        return payload

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    async with PromptPage("open /tmp/readme.md", cursor=(0, 7), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "_schedule_xprompt_assist_warm",
            warmed.append,
        )

        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))

        assert seen[0].kind == "file"
        assert seen[0].target == "/tmp/readme.md"
        assert warmed == []


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

    async with PromptPage("plain_text", cursor=(0, 0), size=(80, 24)) as page:
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
        await page.wait_for(lambda: page.ta._prompt_preview_request_id == 1)
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


async def test_k_on_word_inside_shorthand_argument_runs_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up: list[bool] = []

    async with PromptPage(
        "#foo:: hello world",
        cursor=(0, 8),
        size=(80, 24),
    ) as page:
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: looked_up.append(True) or True,
        )

        await page.press("K")
        await page.pause()

        assert looked_up == [True]
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_k_on_punctuation_inside_shorthand_argument_previews_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[PreviewToken] = []

    def fake_resolve(token: PreviewToken, **_kwargs: object) -> PreviewPayload:
        seen.append(token)
        return PreviewPayload(
            kind_label="xprompt",
            icon="#",
            title="#foo",
            source_path="/tmp/foo.md",
            content="Body\n",
            lexer="markdown",
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_preview.resolve_preview_target",
        fake_resolve,
    )

    text = "#foo:: hello, world"
    async with PromptPage(text, cursor=(0, text.index(",")), size=(80, 24)) as page:
        await page.press("K")
        await page.wait_for(lambda: page.ta._prompt_preview_request_id == 1)
        await page.wait_for(lambda: _top_is_preview(page))

        assert seen
        assert seen[0].kind == "xprompt"
        assert seen[0].target == "foo"
        assert seen[0].raw == text


async def test_k_does_not_overwrite_dot_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="unavailable"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: DefinitionResult(status="unavailable"),
    )

    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"

        await page.press("K")
        await page.pause()
        await page.press(".")

        assert page.text == "three"
