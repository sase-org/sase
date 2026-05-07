"""Tests for pure TUI xprompt argument assist helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
    accepted_xprompt_arg_hint,
    append_input_args,
    append_input_hints,
    build_xprompt_assist_entries,
    colon_args_skeleton,
    detect_xprompt_arg_completion_at_cursor,
    detect_xprompt_arg_hint_at_cursor,
    input_label,
    named_args_skeleton,
    required_inputs,
    visible_inputs,
)
from sase.xprompt.models import UNSET, InputArg, InputType, OutputSpec, XPrompt


def _make_xprompt(
    name: str,
    *,
    source_path: str | None = "config",
    inputs: list[InputArg] | None = None,
    content: str = "body",
) -> XPrompt:
    return XPrompt(
        name=name,
        content=content,
        inputs=inputs or [],
        source_path=source_path,
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


def test_assist_adapter_preserves_structured_catalog_fields(tmp_path: Path) -> None:
    xp = _make_xprompt(
        "typed",
        inputs=[
            InputArg(name="required_word", type=InputType.WORD, default=UNSET),
            InputArg(name="string_default", type=InputType.LINE, default="secret"),
            InputArg(name="null_default", type=InputType.TEXT, default=None),
            InputArg(name="count", type=InputType.INT, default=3),
            InputArg(name="enabled", type=InputType.BOOL, default=False),
            InputArg(
                name="step_output",
                type=InputType.LINE,
                default=UNSET,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            ),
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"typed": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        entries = build_xprompt_assist_entries()

    entry = entries[0]
    assert entry.name == "typed"
    assert entry.insertion == "#typed"
    assert entry.reference_prefix == "#"
    assert entry.kind == "xprompt"
    assert entry.input_signature == (
        "(required_word: word, string_default?: line, null_default?: text, "
        "count?: int, enabled?: bool)"
    )
    assert entry.content_preview == "body"
    assert [
        (inp.name, inp.type, inp.required, inp.default_display, inp.position)
        for inp in entry.inputs
    ] == [
        ("required_word", "word", True, None, 0),
        ("string_default", "line", False, None, 1),
        ("null_default", "text", False, None, 2),
        ("count", "int", False, "3", 3),
        ("enabled", "bool", False, "false", 4),
    ]
    assert [inp.name for inp in visible_inputs(entry)] == [
        "required_word",
        "string_default",
        "null_default",
        "count",
        "enabled",
    ]
    assert [inp.name for inp in required_inputs(entry)] == ["required_word"]


def test_assist_adapter_filters_project_entries(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    project_source = ws / ".xprompts" / "local.md"
    project_source.parent.mkdir()
    project_source.write_text("local")
    global_xp = _make_xprompt("global")
    project_xp = _make_xprompt("local", source_path=str(project_source))
    other_xp = _make_xprompt("other", source_path=str(tmp_path / "other.md"))

    with (
        patch(
            "sase.xprompt.catalog.get_all_xprompts",
            return_value={"global": global_xp},
        ),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch(
            "sase.xprompt.catalog.get_known_project_workspaces",
            return_value={"sase": ws, "other": tmp_path / "other"},
        ),
        patch(
            "sase.xprompt.catalog.load_project_local_xprompts",
            side_effect=[{"local": project_xp}, {"other": other_xp}],
        ),
        patch(
            "sase.xprompt.catalog.get_sase_package_xprompts_dir",
            return_value=tmp_path / "pkg",
        ),
    ):
        entries = build_xprompt_assist_entries(project="sase")

    assert [entry.name for entry in entries] == ["global", "local"]


def test_skeletons_use_required_inputs_only() -> None:
    xp = _make_xprompt(
        "mixed",
        inputs=[
            InputArg(name="first", type=InputType.WORD),
            InputArg(name="second", type=InputType.PATH),
            InputArg(name="optional", type=InputType.BOOL, default=True),
        ],
    )
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"mixed": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert named_args_skeleton(entry) == "#mixed(first=$1, second=$2)$0"
    assert colon_args_skeleton(entry) == "#mixed:$0"


def test_entry_with_only_step_inputs_has_no_user_facing_hints() -> None:
    xp = _make_xprompt(
        "step_only",
        inputs=[
            InputArg(
                name="prior",
                type=InputType.LINE,
                is_step_input=True,
                output_schema=OutputSpec(type="json_schema", schema={"type": "object"}),
            )
        ],
    )

    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"step_only": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert entry.input_signature is None
    assert entry.inputs == ()
    assert named_args_skeleton(entry) == "#step_only"


def test_input_label_formatting_and_rich_rendering() -> None:
    xp = _make_xprompt(
        "rendered",
        inputs=[
            InputArg(name="path", type=InputType.PATH),
            InputArg(name="count", type=InputType.INT, default=2),
            InputArg(name="maybe", type=InputType.LINE, default=None),
        ],
    )
    with (
        patch("sase.xprompt.catalog.get_all_xprompts", return_value={"rendered": xp}),
        patch("sase.xprompt.catalog.get_all_workflows", return_value={}),
        patch("sase.xprompt.catalog.get_known_project_workspaces", return_value={}),
    ):
        entry = build_xprompt_assist_entries()[0]

    assert [input_label(inp) for inp in entry.inputs] == [
        "path: path",
        "count?: int",
        "maybe?: line",
    ]

    text = Text("rendered")
    append_input_hints(text, entry.inputs)
    assert (
        text.plain
        == "rendered\n     path: path\n     count?: int=2\n     maybe?: line?"
    )


def test_append_input_args_preserves_modal_style_for_input_args() -> None:
    text = Text("example")
    append_input_args(
        text,
        [
            InputArg(name="path", type=InputType.PATH),
            InputArg(name="count", type=InputType.INT, default=2),
        ],
    )

    assert text.plain == "example\n     path\n     count=2"
    spans = [(span.start, span.end, span.style) for span in text.spans]
    assert spans == [
        (13, 17, "#D7AF87"),
        (23, 28, "dim #D7AF87"),
        (28, 30, "dim #888888"),
    ]


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
