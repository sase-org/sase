"""Tests for prompt-input xprompt completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)
from sase.ace.tui.widgets.xprompt_completion import (
    build_xprompt_completion_candidates,
    is_xprompt_like_token,
)

from ._completion_helpers import CompletionTestApp


def _entry(
    name: str,
    *,
    prefix: str = "#",
    kind: str = "xprompt",
    inputs: tuple[XPromptInputHint, ...] = (),
    is_skill: bool = False,
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind=kind,
        input_signature=None,
        inputs=inputs,
        content_preview=None,
        is_skill=is_skill,
    )


def _input(
    name: str,
    type_: str,
    *,
    required: bool = True,
    default_display: str | None = None,
    position: int = 0,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=required,
        default_display=default_display,
        position=position,
    )


def test_xprompt_like_token_accepts_standalone_marker() -> None:
    assert is_xprompt_like_token("#foo") is True
    assert is_xprompt_like_token("#!foo") is True
    assert is_xprompt_like_token("#!") is True
    assert is_xprompt_like_token("foo") is False


def test_xprompt_like_token_accepts_bare_slash_skill_tokens() -> None:
    assert is_xprompt_like_token("/") is True
    assert is_xprompt_like_token("/sase_plan") is True
    assert is_xprompt_like_token("/sase_plan2") is True
    assert is_xprompt_like_token("/tmp/foo") is False
    assert is_xprompt_like_token("/sase-plan") is False
    assert is_xprompt_like_token("foo") is False


def test_xprompt_completion_uses_kind_aware_insertions() -> None:
    entries = [
        _entry("commit"),
        _entry("gh", kind="embeddable_workflow"),
        _entry("sync", prefix="#!", kind="standalone_workflow"),
    ]
    with patch(
        "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
        return_value=entries,
    ):
        candidates, shared = build_xprompt_completion_candidates("#s")

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("#!sync", "#!sync", "sync")
    ]


def test_standalone_marker_filters_to_standalone_workflows() -> None:
    entries = [
        _entry("sync", prefix="#!", kind="standalone_workflow"),
        _entry("setup"),
        _entry("split", prefix="#!", kind="xprompt"),
        _entry("send", kind="embeddable_workflow"),
    ]
    with patch(
        "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
        return_value=entries,
    ):
        candidates, shared = build_xprompt_completion_candidates("#!s")

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("#!split", "#!split", "split"),
        ("#!sync", "#!sync", "sync"),
    ]


def test_xprompt_completion_finds_builtin_cd_workflow() -> None:
    candidates, _ = build_xprompt_completion_candidates("#c")
    by_name = {candidate.name: candidate for candidate in candidates}

    assert "cd" in by_name
    assert by_name["cd"].display == "#cd"
    assert by_name["cd"].insertion == "#cd"


def test_xprompt_candidates_carry_assist_metadata() -> None:
    entry = _entry("review", inputs=(_input("path", "path"),))
    with patch(
        "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
        return_value=[entry],
    ):
        candidates, _ = build_xprompt_completion_candidates("#r")

    assert candidates[0].metadata is entry


def test_slash_skill_completion_filters_to_skills_and_uses_slash_insertions() -> None:
    entries = [
        _entry("sase_plan", inputs=(_input("topic", "line"),), is_skill=True),
        _entry("sase_changespecs", is_skill=True),
        _entry("sase_regular"),
        _entry("review", is_skill=True),
    ]
    with patch(
        "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
        return_value=entries,
    ):
        candidates, shared = build_xprompt_completion_candidates("/sase_")

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("/sase_changespecs", "/sase_changespecs", "sase_changespecs"),
        ("/sase_plan", "/sase_plan", "sase_plan"),
    ]
    assert candidates[1].metadata is entries[0]


def test_slash_skill_completion_extends_shared_prefix() -> None:
    entries = [
        _entry("sase_plan", is_skill=True),
        _entry("sase_questions", is_skill=True),
        _entry("sample", is_skill=True),
    ]
    with patch(
        "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
        return_value=entries,
    ):
        candidates, shared = build_xprompt_completion_candidates("/s")

    assert [c.insertion for c in candidates] == [
        "/sample",
        "/sase_plan",
        "/sase_questions",
    ]
    assert shared == "a"


async def test_completion_panel_shows_required_input_names_and_types() -> None:
    entries = [
        _entry("review", inputs=(_input("path", "path"),)),
        _entry("ship"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert "path: path" in rendered.plain


async def test_completion_panel_renders_optional_inputs_distinctly() -> None:
    optional = _input(
        "count",
        "int",
        required=False,
        default_display="2",
    )
    entries = [
        _entry("configure", inputs=(optional,)),
        _entry("deploy"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert "count?: int=2" in rendered.plain
        assert "rgb(215,175,135) dim" in {str(span.style) for span in rendered.spans}


async def test_completion_panel_handles_xprompt_with_no_visible_inputs() -> None:
    entries = [_entry("plain"), _entry("typed", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert "#plain  xprompt" in rendered.plain


async def test_standalone_marker_single_candidate_inserts_canonical_reference() -> None:
    entries = [
        _entry("send"),
        _entry("sync", prefix="#!", kind="standalone_workflow"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#!s")
        ta.cursor_location = (0, 3)
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "#!sync"
    assert ta._file_completion_active is False


async def test_slash_skill_single_candidate_inserts_slash_reference() -> None:
    entries = [
        _entry("sase_plan", inputs=(_input("topic", "line"),), is_skill=True),
        _entry("sase_regular"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("/sase_p")
        ta.cursor_location = (0, len("/sase_p"))
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "/sase_plan"
    assert ta._file_completion_active is False
    assert ta._active_xprompt_arg_hint is None


async def test_slash_skill_multiple_candidates_opens_completion_panel() -> None:
    entries = [
        _entry("sase_plan", is_skill=True),
        _entry("sase_questions", is_skill=True),
        _entry("send"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("/sase_")
        ta.cursor_location = (0, len("/sase_"))
        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(
                "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
                return_value=entries,
            ),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert "/sase_plan  skill" in rendered.plain
        assert "/sase_questions  skill" in rendered.plain
