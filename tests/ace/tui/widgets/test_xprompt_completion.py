"""Tests for prompt-input xprompt completion."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
    build_xprompt_assist_entries,
)
from sase.ace.tui.widgets.xprompt_completion import (
    XPromptTokenSpan,
    build_xprompt_completion_candidates,
    extract_xprompt_token_around_cursor,
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
    description: str | None = None,
) -> XPromptAssistEntry:
    # Skills carry the namespaced ``skills/foo`` xprompt reference name while
    # keeping ``foo`` as the provider skill name matched by ``/`` completion.
    reference_name = f"skills/{name}" if is_skill else name
    return XPromptAssistEntry(
        name=reference_name,
        insertion=f"{prefix}{reference_name}",
        reference_prefix=prefix,
        kind=kind,
        input_signature=None,
        inputs=inputs,
        content_preview=None,
        description=description,
        is_skill=is_skill,
        skill_name=name if is_skill else None,
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


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


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


def test_extract_xprompt_token_around_cursor_clamps_to_reference_name() -> None:
    assert extract_xprompt_token_around_cursor("(see #ss.", 8) == XPromptTokenSpan(
        5, 8, "#ss", clamped=True
    )
    assert extract_xprompt_token_around_cursor("(see #ss.", 9) is None
    assert extract_xprompt_token_around_cursor("(see #ss", 8) == XPromptTokenSpan(
        5, 8, "#ss", clamped=False
    )
    assert extract_xprompt_token_around_cursor("(#n)", 3) == XPromptTokenSpan(
        1, 3, "#n", clamped=False
    )
    assert extract_xprompt_token_around_cursor("#bd/wo.", 6) == XPromptTokenSpan(
        0, 6, "#bd/wo", clamped=True
    )
    assert extract_xprompt_token_around_cursor("#!sy.", 4) == XPromptTokenSpan(
        0, 4, "#!sy", clamped=True
    )
    assert extract_xprompt_token_around_cursor("#", 1) == XPromptTokenSpan(
        0, 1, "#", clamped=False
    )
    assert extract_xprompt_token_around_cursor("~/foo.py", 5) is None
    assert extract_xprompt_token_around_cursor(".#ss", 4) is None


def test_clamped_xprompt_completion_excludes_dotted_names() -> None:
    entry = _entry("foo.bar")
    span = extract_xprompt_token_around_cursor("#foo.b", 4)
    assert span == XPromptTokenSpan(0, 4, "#foo", clamped=True)

    clamped, _ = build_xprompt_completion_candidates(
        span.token,
        entries=[entry],
        inline_reference_only=span.clamped,
    )
    unclamped, _ = build_xprompt_completion_candidates("#foo", entries=[entry])

    assert clamped == []
    assert [candidate.insertion for candidate in unclamped] == ["#foo.bar"]


def test_xprompt_completion_uses_kind_aware_insertions() -> None:
    entries = [
        _entry("commit"),
        _entry("gh", kind="embeddable_workflow"),
        _entry("sync", prefix="#!", kind="standalone_workflow"),
    ]
    candidates, shared = build_xprompt_completion_candidates("#s", entries=entries)

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
    candidates, shared = build_xprompt_completion_candidates("#!s", entries=entries)

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("#!split", "#!split", "split"),
        ("#!sync", "#!sync", "sync"),
    ]


def test_xprompt_completion_omits_removed_directory_workflow() -> None:
    candidates, _ = build_xprompt_completion_candidates(
        "#c",
        entries=build_xprompt_assist_entries(),
    )
    by_name = {candidate.name: candidate for candidate in candidates}

    assert "cd" not in by_name


def test_xprompt_candidates_carry_assist_metadata() -> None:
    entry = _entry("review", inputs=(_input("path", "path"),))
    candidates, _ = build_xprompt_completion_candidates("#r", entries=[entry])

    assert candidates[0].metadata is entry


def test_slash_skill_completion_filters_to_skills_and_uses_slash_insertions() -> None:
    entries = [
        _entry("sase_plan", inputs=(_input("topic", "line"),), is_skill=True),
        _entry("sase_changespecs", is_skill=True),
        _entry("sase_regular"),
        _entry("review", is_skill=True),
    ]
    candidates, shared = build_xprompt_completion_candidates(
        "/sase_",
        entries=entries,
    )

    assert shared == ""
    assert [(c.display, c.insertion, c.name) for c in candidates] == [
        ("/sase_changespecs", "/sase_changespecs", "sase_changespecs"),
        ("/sase_plan", "/sase_plan", "sase_plan"),
    ]
    assert candidates[1].metadata is entries[0]


def test_slash_skill_completion_finds_packaged_sase_skills() -> None:
    candidates, _ = build_xprompt_completion_candidates(
        "/sase_",
        entries=build_xprompt_assist_entries(),
    )
    by_name = {candidate.name: candidate for candidate in candidates}

    assert "sase_plan" in by_name
    assert "sase_questions" in by_name
    assert by_name["sase_plan"].display == "/sase_plan"
    assert by_name["sase_plan"].insertion == "/sase_plan"
    assert by_name["sase_plan"].metadata.is_skill is True


def test_slash_skill_completion_extends_shared_prefix() -> None:
    entries = [
        _entry("sase_plan", is_skill=True),
        _entry("sase_questions", is_skill=True),
        _entry("sample", is_skill=True),
    ]
    candidates, shared = build_xprompt_completion_candidates("/s", entries=entries)

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
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert "path: path" in rendered.plain


async def test_completion_panel_shows_xprompt_description() -> None:
    entries = [
        _entry("review", description="Review a selected diff."),
        _entry("ship"),
    ]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert "#review  xprompt  Review a selected diff." in rendered.plain


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
        _seed_entries(ta, entries)
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
        _seed_entries(ta, entries)
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
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "#!sync "
    assert ta._file_completion_active is False


async def test_single_candidate_xprompt_without_inputs_adds_trailing_space() -> None:
    entries = [_entry("none")]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#n")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "#none "
    assert ta.cursor_location == (0, len("#none "))
    assert ta._active_xprompt_arg_hint is None


async def test_single_candidate_xprompt_without_inputs_skips_space_before_punctuation() -> (
    None
):
    entries = [_entry("none")]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("(#n)")
        ta.cursor_location = (0, len("(#n"))
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "(#none)"
    assert ta.cursor_location == (0, len("(#none"))
    assert ta._active_xprompt_arg_hint is None


async def test_single_candidate_xprompt_before_period_preserves_period() -> None:
    entries = [_entry("none")]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("(see #n.")
        ta.cursor_location = (0, len("(see #n"))
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "(see #none."
    assert ta.cursor_location == (0, len("(see #none"))
    assert ta._active_xprompt_arg_hint is None


async def test_single_candidate_xprompt_skeleton_lands_before_period() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("(see #r.")
        ta.cursor_location = (0, len("(see #r"))
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "(see #review:."
    assert ta.cursor_location == (0, len("(see #review:"))
    assert ta._active_xprompt_arg_hint is not None


async def test_single_candidate_xprompt_required_path_inserts_colon() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "#review:"
    assert ta.cursor_location == (0, len("#review:"))
    assert ta._active_xprompt_arg_hint is not None


async def test_single_candidate_xprompt_required_text_inserts_double_colon_space() -> (
    None
):
    entries = [_entry("write", inputs=(_input("body", "text"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#w")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    # End-of-line acceptance widens the ``::`` skeleton to the free-form ``:: ``
    # shorthand and parks the cursor after the delimiter space, which ends
    # structured argument hinting.
    assert ta.text == "#write:: "
    assert ta.cursor_location == (0, len("#write:: "))
    assert ta._active_xprompt_arg_hint is None


async def test_single_candidate_xprompt_many_inputs_places_cursor_in_parens() -> None:
    entries = [
        _entry(
            "many",
            inputs=(
                _input("path", "path"),
                _input("body", "text", position=1),
            ),
        )
    ]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#m")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    assert ta.text == "#many()"
    assert "$0" not in ta.text
    assert ta.cursor_location == (0, len("#many("))
    assert ta._active_xprompt_arg_hint is not None


async def test_panel_acceptance_uses_xprompt_completion_skeleton() -> None:
    entries = [
        _entry("many", inputs=(_input("path", "path"), _input("body", "text"))),
        _entry("more"),
    ]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#m")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        await pilot.press("ctrl+t")
        await pilot.press("enter")

    assert ta.text == "#many()"
    assert ta.cursor_location == (0, len("#many("))


async def test_ctrl_t_required_text_before_existing_text_keeps_single_space() -> None:
    entries = [_entry("ask", inputs=(_input("body", "text"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("#a here")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

    # Mid-line acceptance keeps ``::`` so the existing following space is the
    # single delimiter rather than a doubled space.
    assert ta.text == "#ask:: here"


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
        _seed_entries(ta, entries)
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
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt"
        assert "/sase_plan  skill" in rendered.plain
        assert "/sase_questions  skill" in rendered.plain
