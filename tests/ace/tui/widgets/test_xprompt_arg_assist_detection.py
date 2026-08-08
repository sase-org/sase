"""Tests for detecting TUI xprompt argument assist contexts."""

from __future__ import annotations

from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
    accepted_xprompt_arg_hint,
    detect_xprompt_arg_completion_at_cursor,
    detect_xprompt_arg_hint_at_cursor,
)


def _input_hint(name: str, type_: str = "word", position: int = 0) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
    )


def _entry(
    name: str,
    *inputs: XPromptInputHint,
    prefix: str = "#",
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind="xprompt",
        input_signature=None,
        inputs=tuple(inputs),
        content_preview=None,
    )


def test_detect_typed_colon_and_paren_argument_positions() -> None:
    entries = [
        _entry(
            "review",
            _input_hint("path", "path"),
            _input_hint("count", "int", 1),
        ),
        _entry("sync", _input_hint("branch"), prefix="#!"),
        _entry("ns/foo", _input_hint("value")),
    ]

    cases = [
        ("#review:", 0, "colon"),
        ("#!sync:", 0, "colon"),
        ("#ns/foo:", 0, "colon"),
        ("#ns__foo:", 0, "colon"),
        ("#review!!:", 0, "colon"),
        ("#review??:", 0, "colon"),
        ("#review(", 0, "paren"),
        ("#review(path=", 0, "paren"),
        ("#review:foo,", 1, "colon"),
    ]

    for prompt, active_index, trigger_mode in cases:
        hint = detect_xprompt_arg_hint_at_cursor(prompt, len(prompt), entries)
        assert hint is not None
        assert hint.active_input_index == active_index
        assert hint.trigger_mode == trigger_mode


def test_detect_typed_argument_positions_rejects_broad_cases() -> None:
    entries = [_entry("review", _input_hint("path", "path"))]

    for prompt in [
        "#unknown:",
        "#review+",
        "https://example.test/#review:",
        "foo#review:",
        "#review: text",
        "#review(done)",
    ]:
        assert detect_xprompt_arg_hint_at_cursor(prompt, len(prompt), entries) is None


def test_detect_typed_argument_hint_ignores_double_colon_free_text() -> None:
    entries = [_entry("ask", _input_hint("body", "text"))]

    assert (
        detect_xprompt_arg_hint_at_cursor("#ask:: after", len("#ask::"), entries)
        is None
    )


def test_accepted_xprompt_arg_hint_requires_exact_inserted_reference() -> None:
    entries = [
        _entry("review", _input_hint("path", "path")),
        _entry("plain"),
    ]

    hint = accepted_xprompt_arg_hint("#review", 0, len("#review"), entries)
    assert hint is not None
    assert hint.reference_text == "#review"

    assert accepted_xprompt_arg_hint("#plain", 0, len("#plain"), entries) is None
    assert accepted_xprompt_arg_hint("#review:", 0, len("#review:"), entries) is None


def test_detects_type_aware_arg_completion_contexts() -> None:
    entries = [
        _entry(
            "review",
            _input_hint("path", "path"),
            _input_hint("enabled", "bool", 1),
            _input_hint("count", "int", 2),
        )
    ]

    path_ctx = detect_xprompt_arg_completion_at_cursor(
        "#review:", len("#review:"), entries
    )
    assert path_ctx is not None
    assert path_ctx.completion_kind == "xprompt_arg_path"
    assert path_ctx.active_input is not None
    assert path_ctx.active_input.name == "path"
    assert path_ctx.value_start == len("#review:")
    assert path_ctx.value_end == len("#review:")
    assert path_ctx.token == ""

    bool_ctx = detect_xprompt_arg_completion_at_cursor(
        "#review(enabled=)", len("#review(enabled="), entries
    )
    assert bool_ctx is not None
    assert bool_ctx.completion_kind == "xprompt_arg_value"
    assert bool_ctx.active_input is not None
    assert bool_ctx.active_input.name == "enabled"
    assert bool_ctx.token == ""

    name_ctx = detect_xprompt_arg_completion_at_cursor(
        "#review(path=foo, e", len("#review(path=foo, e"), entries
    )
    assert name_ctx is not None
    assert name_ctx.completion_kind == "xprompt_arg_name"
    assert name_ctx.token == "e"
    assert name_ctx.used_arg_names == frozenset({"path"})

    int_ctx = detect_xprompt_arg_completion_at_cursor(
        "#review(count=", len("#review(count="), entries
    )
    assert int_ctx is not None
    assert int_ctx.completion_kind == "xprompt_arg_type_hint"


def test_detects_agent_arg_completion_contexts_for_fork_forms() -> None:
    entries = [_entry("fork", _input_hint("name", "agent"))]

    trailing_cases = [
        "#fork:",
        "#fork: bar",
        "foo #fork: bar",
        "#fork:c bar",
    ]
    for prompt in trailing_cases:
        cursor_offset = prompt.index(":") + 1
        ctx = detect_xprompt_arg_completion_at_cursor(prompt, cursor_offset, entries)
        assert ctx is not None
        assert ctx.completion_kind == "xprompt_arg_agent"
        assert ctx.active_input is not None
        assert ctx.active_input.name == "name"
        assert ctx.value_start == cursor_offset
        assert ctx.value_end == cursor_offset
        assert ctx.token == ""

    colon_ctx = detect_xprompt_arg_completion_at_cursor(
        "#fork:co", len("#fork:co"), entries
    )
    assert colon_ctx is not None
    assert colon_ctx.completion_kind == "xprompt_arg_agent"
    assert colon_ctx.active_input is not None
    assert colon_ctx.active_input.name == "name"
    assert colon_ctx.token == "co"

    paren_ctx = detect_xprompt_arg_completion_at_cursor(
        "#fork(co", len("#fork(co"), entries
    )
    assert paren_ctx is not None
    assert paren_ctx.completion_kind == "xprompt_arg_agent"
    assert paren_ctx.value_start == len("#fork(")
    assert paren_ctx.token == "co"

    assert (
        detect_xprompt_arg_completion_at_cursor("#fork: ag", len("#fork: ag"), entries)
        is None
    )


def test_repeatable_agent_context_tracks_selected_values_and_full_active_range() -> (
    None
):
    entries = [
        _entry(
            "fork",
            XPromptInputHint(
                name="names",
                type="agent",
                required=False,
                default_display=None,
                position=0,
                repeatable=True,
            ),
        )
    ]

    colon = "#fork:planner,co,reviewer.@"
    colon_cursor = colon.index("co") + 2
    colon_ctx = detect_xprompt_arg_completion_at_cursor(colon, colon_cursor, entries)
    assert colon_ctx is not None
    assert colon_ctx.completion_kind == "xprompt_arg_agent"
    assert colon_ctx.token == "co"
    assert colon_ctx.value_start == colon.index("co")
    assert colon_ctx.value_end == colon.index(",reviewer")
    assert colon_ctx.selected_values == frozenset({"planner", "reviewer.@"})

    paren = "#fork(co, planner)"
    paren_ctx = detect_xprompt_arg_completion_at_cursor(
        paren, paren.index("co") + 2, entries
    )
    assert paren_ctx is not None
    assert paren_ctx.value_start == paren.index("co")
    assert paren_ctx.value_end == paren.index(", planner")
    assert paren_ctx.selected_values == frozenset({"planner"})


def test_agent_arg_completion_is_inert_in_fences_and_disabled_regions() -> None:
    entries = [_entry("fork", _input_hint("name", "agent"))]

    fenced = "```\n#fork:co\n```"
    assert (
        detect_xprompt_arg_completion_at_cursor(fenced, fenced.index("co") + 2, entries)
        is None
    )

    disabled = "%xprompts_enabled:false\n#fork:co\n%xprompts_enabled:true\n"
    assert (
        detect_xprompt_arg_completion_at_cursor(
            disabled, disabled.index("co") + 2, entries
        )
        is None
    )


def test_fork_agent_arg_completion_after_earlier_xprompt_reference() -> None:
    entries = [
        _entry("gh", _input_hint("project")),
        _entry("fork", _input_hint("name", "agent")),
    ]

    prompt = "#gh:sase #fork:"
    ctx = detect_xprompt_arg_completion_at_cursor(prompt, len(prompt), entries)
    assert ctx is not None
    assert ctx.completion_kind == "xprompt_arg_agent"
    assert ctx.active_input is not None
    assert ctx.active_input.name == "name"
    assert ctx.value_start == len(prompt)
    assert ctx.value_end == len(prompt)
    assert ctx.token == ""


def test_fork_agent_arg_completion_rejected_inside_double_colon_free_text() -> None:
    entries = [
        _entry("ask", _input_hint("body", "text")),
        _entry("fork", _input_hint("name", "agent")),
    ]

    prompt = "#ask:: after #fork:"
    assert detect_xprompt_arg_completion_at_cursor(prompt, len(prompt), entries) is None
