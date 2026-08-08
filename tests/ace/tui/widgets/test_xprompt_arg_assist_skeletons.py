"""Tests for TUI xprompt argument completion skeletons."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
    build_xprompt_assist_entries,
    colon_args_skeleton,
    named_args_skeleton,
    xprompt_completion_skeleton,
    xprompt_completion_suffix_skeleton,
)
from sase.xprompt.models import InputArg, InputType, XPrompt


def _input_hint(name: str, type_: str = "word", position: int = 0) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
    )


def _optional_input_hint(
    name: str, type_: str = "word", position: int = 0
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=False,
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


def test_skeletons_use_required_inputs_only() -> None:
    xp = XPrompt(
        name="mixed",
        content="body",
        source_path="config",
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


def test_completion_skeletons_match_required_input_shapes() -> None:
    assert xprompt_completion_skeleton(_entry("none")) == "#none "
    assert (
        xprompt_completion_skeleton(_entry("optional", _optional_input_hint("count")))
        == "#optional "
    )
    assert xprompt_completion_skeleton(_entry("path", _input_hint("path", "path"))) == (
        "#path:"
    )
    assert xprompt_completion_skeleton(_entry("text", _input_hint("body", "text"))) == (
        "#text::"
    )
    assert (
        xprompt_completion_skeleton(
            _entry("many", _input_hint("path", "path"), _input_hint("body", "text"))
        )
        == "#many($0)"
    )
    assert (
        xprompt_completion_skeleton(_entry("run", _input_hint("target"), prefix="#!"))
        == "#!run:"
    )


def test_completion_skeleton_suppresses_no_required_space_before_punctuation() -> None:
    none_entry = _entry("none")
    optional_entry = _entry("optional", _optional_input_hint("count"))

    for next_char in (")", ".", "!"):
        assert xprompt_completion_skeleton(none_entry, next_char=next_char) == "#none"

    assert xprompt_completion_skeleton(none_entry, next_char="a") == "#none "
    assert xprompt_completion_skeleton(none_entry, next_char=None) == "#none "
    assert xprompt_completion_skeleton(none_entry) == "#none "

    assert xprompt_completion_skeleton(optional_entry, next_char="]") == "#optional"
    assert xprompt_completion_skeleton(optional_entry, next_char="a") == "#optional "
    assert xprompt_completion_skeleton(optional_entry, next_char=None) == "#optional "


def test_completion_skeleton_next_char_does_not_affect_required_inputs() -> None:
    assert (
        xprompt_completion_skeleton(
            _entry("path", _input_hint("path", "path")),
            next_char=")",
        )
        == "#path:"
    )
    assert (
        xprompt_completion_skeleton(
            _entry("text", _input_hint("body", "text")),
            append_text_arg_space=True,
            next_char=")",
        )
        == "#text:: "
    )
    assert (
        xprompt_completion_skeleton(
            _entry("many", _input_hint("path", "path"), _input_hint("body", "text")),
            next_char=")",
        )
        == "#many($0)"
    )


def test_completion_skeleton_appends_text_arg_space_only_for_single_required_text() -> (
    None
):
    text_entry = _entry("text", _input_hint("body", "text"))
    # The context-free default is unchanged: a bare ``::``.
    assert xprompt_completion_skeleton(text_entry) == "#text::"
    # An end-of-line accept widens the single required-text skeleton to ``:: ``
    # (the free-form double-colon shorthand is ``:: `` followed by text).
    assert (
        xprompt_completion_skeleton(text_entry, append_text_arg_space=True)
        == "#text:: "
    )
    # The flag is a no-op for every other input shape.
    assert (
        xprompt_completion_skeleton(_entry("none"), append_text_arg_space=True)
        == "#none "
    )
    assert (
        xprompt_completion_skeleton(
            _entry("optional", _optional_input_hint("count")),
            append_text_arg_space=True,
        )
        == "#optional "
    )
    assert (
        xprompt_completion_skeleton(
            _entry("path", _input_hint("path", "path")), append_text_arg_space=True
        )
        == "#path:"
    )
    assert (
        xprompt_completion_skeleton(
            _entry("many", _input_hint("path", "path"), _input_hint("body", "text")),
            append_text_arg_space=True,
        )
        == "#many($0)"
    )
    assert (
        xprompt_completion_skeleton(
            _entry("run", _input_hint("target"), prefix="#!"),
            append_text_arg_space=True,
        )
        == "#!run:"
    )


def test_completion_suffix_skeleton_strips_existing_hash_trigger() -> None:
    assert xprompt_completion_suffix_skeleton(_entry("none")) == "none "
    assert xprompt_completion_suffix_skeleton(_entry("none"), next_char=")") == "none"
    assert xprompt_completion_suffix_skeleton(_entry("none"), next_char="a") == "none "
    assert (
        xprompt_completion_suffix_skeleton(
            _entry("run", _input_hint("target"), prefix="#!")
        )
        == "!run:"
    )
    text_entry = _entry("text", _input_hint("body", "text"))
    assert xprompt_completion_suffix_skeleton(text_entry) == "text::"
    assert (
        xprompt_completion_suffix_skeleton(text_entry, append_text_arg_space=True)
        == "text:: "
    )
