"""Pure-function tests for prompt VCS xprompt deletion and MRU cycling."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from sase.ace.tui.widgets._vcs_mru_cycling import (
    _VcsMruCycleEdit,
    _VcsXPromptDeleteEdit,
    _cycle_vcs_mru_text,
    _delete_vcs_xprompt_text,
)

_TEST_EMBEDDED_VCS_PATTERN = re.compile(
    r"(?:^|(?<=\s))#(?:gh|git|spy|cd)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s"
)


@contextmanager
def _patched_vcs_parsing() -> Iterator[None]:
    import sase.xprompt._parsing as parsing
    import sase.xprompt._parsing_vcs_refs as vcs_refs

    parsing._VCS_UNDERSCORE_NORMALIZER = None
    vcs_refs._VCS_UNDERSCORE_NORMALIZER = None
    with (
        patch(
            "sase.xprompt._parsing._get_embedded_vcs_tag_pattern",
            return_value=_TEST_EMBEDDED_VCS_PATTERN,
        ),
        patch(
            "sase.workspace_provider.get_workflow_names",
            return_value={"gh", "git", "spy", "cd"},
        ),
    ):
        yield
    parsing._VCS_UNDERSCORE_NORMALIZER = None
    vcs_refs._VCS_UNDERSCORE_NORMALIZER = None


def _cycle(
    text: str,
    *,
    cursor_offset: int | None = None,
    current_index: int | None = None,
    mru: list[str] | None = None,
    key: str = "ctrl+p",
) -> _VcsMruCycleEdit:
    with _patched_vcs_parsing():
        edit = _cycle_vcs_mru_text(
            text=text,
            cursor_offset=len(text) if cursor_offset is None else cursor_offset,
            mru=mru or ["#git:foo", "#git:bar", "#git:baz"],
            current_index=current_index,
            key=key,  # type: ignore[arg-type]
        )
    assert edit is not None
    return edit


def _delete(
    text: str,
    *,
    cursor_offset: int | None = None,
) -> _VcsXPromptDeleteEdit:
    with _patched_vcs_parsing():
        edit = _delete_vcs_xprompt_text(
            text,
            len(text) if cursor_offset is None else cursor_offset,
        )
    assert edit is not None
    return edit


def _delete_or_none(
    text: str,
    *,
    cursor_offset: int | None = None,
) -> _VcsXPromptDeleteEdit | None:
    with _patched_vcs_parsing():
        return _delete_vcs_xprompt_text(
            text,
            len(text) if cursor_offset is None else cursor_offset,
        )


def test_empty_prompt_cycles_to_most_recent_entry() -> None:
    edit = _cycle("")
    assert edit.text == "#git:foo "
    assert edit.cursor_offset == len("#git:foo ")
    assert edit.mru_index == 0


def test_replaces_first_existing_tag_and_preserves_body() -> None:
    edit = _cycle("#git:foo fix the bug")
    assert edit.text == "#git:bar fix the bug"
    assert edit.cursor_offset == len("#git:bar fix the bug")
    assert edit.mru_index == 1


def test_current_tag_lookup_advances_forward() -> None:
    edit = _cycle("#git:bar fix the bug")
    assert edit.text == "#git:baz fix the bug"
    assert edit.mru_index == 2


def test_prefilled_humanized_tag_resumes_ring_at_matching_index() -> None:
    """A prompt prefilled with a humanized tag resumes the (humanized) ring.

    Because ``load_launchable_vcs_xprompt_mru`` now returns humanized entries
    and the widget inserts those humanized tags, the current prompt tag and the
    MRU entries are in the same (display) form, so the current tag is found by
    normalized equality and the cycle advances from its position rather than
    restarting at the most-recent entry.
    """
    edit = _cycle(
        "#git:widgets do work",
        mru=["#git:alpha", "#git:widgets", "#git:beta"],
        cursor_offset=len("#git:widgets do work"),
    )
    assert edit.mru_index == 2
    assert edit.replacement == "#git:beta"
    assert edit.text == "#git:beta do work"


def test_current_tag_lookup_normalizes_underscore_refs() -> None:
    edit = _cycle("#gh_sase fix", mru=["#gh:sase", "#gh:other"])
    assert edit.text == "#gh:other fix"
    assert edit.mru_index == 1


def test_oldest_entry_cycles_to_empty_stop() -> None:
    edit = _cycle("#git:baz")
    assert edit.text == ""
    assert edit.cursor_offset == 0
    assert edit.mru_index == 3
    assert edit.replacement == ""


def test_oldest_entry_with_body_cycles_to_empty_stop() -> None:
    edit = _cycle("#git:baz fix the bug")
    assert edit.text == "fix the bug"
    assert edit.cursor_offset == len("fix the bug")
    assert edit.mru_index == 3


def test_empty_stop_continues_to_most_recent_entry() -> None:
    edit = _cycle("fix the bug", current_index=2, mru=["#git:foo", "#git:bar"])
    assert edit.text == "#git:foo fix the bug"
    assert edit.mru_index == 0


def test_replaces_only_first_tag() -> None:
    edit = _cycle("#git:foo first\n---\n#git:baz second")
    assert edit.text == "#git:bar first\n---\n#git:baz second"


def test_tag_followed_by_newline_preserves_newline() -> None:
    edit = _cycle("#git:foo\nfix")
    assert edit.text == "#git:bar\nfix"


def test_tag_at_end_gets_trailing_space() -> None:
    edit = _cycle("#git:foo")
    assert edit.text == "#git:bar "
    assert edit.cursor_offset == len("#git:bar ")


def test_prepends_when_prompt_has_no_tag() -> None:
    edit = _cycle("fix the bug")
    assert edit.text == "#git:foo fix the bug"
    assert edit.cursor_offset == len("#git:foo fix the bug")
    assert edit.mru_index == 0


def test_tag_inside_fenced_block_is_not_replaced() -> None:
    """Quoted tags in code blocks must be preserved; cycling prepends instead."""
    text = "Fix the launcher:\n```\nsase run #git:quoted do thing\n```\n"
    edit = _cycle(text)
    assert edit.text.startswith("#git:foo ")
    assert "#git:quoted" in edit.text


def test_second_prepend_press_continues_from_previous_index() -> None:
    first = _cycle("fix the bug", mru=["#git:foo", "#git:bar"])
    second = _cycle(
        first.text,
        current_index=first.mru_index,
        mru=["#git:foo", "#git:bar"],
    )
    assert second.text == "#git:bar fix the bug"
    assert second.mru_index == 1


def test_prepend_inserts_after_frontmatter_whitespace_and_directives() -> None:
    text = "---\nxprompts: {}\n---\n  %i:a %wait Fix it"
    edit = _cycle(text)
    assert edit.text == "---\nxprompts: {}\n---\n  %i:a %wait #git:foo Fix it"
    assert edit.start_offset == len("---\nxprompts: {}\n---\n  %i:a %wait ")


def test_cursor_before_replaced_span_is_unchanged() -> None:
    text = "intro #git:foo fix"
    edit = _cycle(text, cursor_offset=2)
    assert edit.text == "intro #git:bar fix"
    assert edit.cursor_offset == 2


def test_cursor_inside_replaced_span_snaps_after_new_tag() -> None:
    text = "intro #git:foo fix"
    tag_start = text.index("#git:foo")
    edit = _cycle(text, cursor_offset=tag_start + 3)
    assert edit.cursor_offset == tag_start + len("#git:bar")


def test_cursor_after_replaced_span_shifts_by_length_delta() -> None:
    text = "#git:foo fix"
    edit = _cycle(text, mru=["#git:foo", "#git:longer"])
    assert edit.text == "#git:longer fix"
    assert edit.cursor_offset == len("#git:longer fix")


def test_cursor_before_prepend_point_is_unchanged() -> None:
    text = "---\nxprompts: {}\n---\nFix it"
    edit = _cycle(text, cursor_offset=4)
    assert edit.text == "---\nxprompts: {}\n---\n#git:foo Fix it"
    assert edit.cursor_offset == 4


def test_ctrl_n_cycles_backward_to_previous_entry() -> None:
    edit = _cycle("#git:bar", key="ctrl+n")
    assert edit.text == "#git:foo "
    assert edit.cursor_offset == len("#git:foo ")
    assert edit.mru_index == 0


def test_ctrl_n_from_most_recent_entry_reaches_empty_stop() -> None:
    edit = _cycle("#git:foo", key="ctrl+n")
    assert edit.text == ""
    assert edit.cursor_offset == 0
    assert edit.mru_index == 3
    assert edit.replacement == ""


def test_ctrl_n_from_most_recent_entry_with_body_deletes_tag() -> None:
    edit = _cycle("#git:foo fix the bug", key="ctrl+n")
    assert edit.text == "fix the bug"
    assert edit.cursor_offset == len("fix the bug")
    assert edit.mru_index == 3


def test_ctrl_n_no_tag_selects_oldest_entry() -> None:
    edit = _cycle("fix the bug", key="ctrl+n")
    assert edit.text == "#git:baz fix the bug"
    assert edit.cursor_offset == len("#git:baz fix the bug")
    assert edit.mru_index == 2


def test_ctrl_n_empty_prompt_selects_oldest_entry() -> None:
    edit = _cycle("", key="ctrl+n")
    assert edit.text == "#git:baz "
    assert edit.cursor_offset == len("#git:baz ")
    assert edit.mru_index == 2


def test_ctrl_n_empty_stop_continues_to_oldest_entry() -> None:
    edit = _cycle(
        "fix the bug",
        current_index=2,
        mru=["#git:foo", "#git:bar"],
        key="ctrl+n",
    )
    assert edit.text == "#git:bar fix the bug"
    assert edit.mru_index == 1


def test_ctrl_n_lookup_normalizes_underscore_refs() -> None:
    edit = _cycle("#gh_other fix", mru=["#gh:sase", "#gh:other"], key="ctrl+n")
    assert edit.text == "#gh:sase fix"
    assert edit.mru_index == 0


def test_ctrl_p_then_ctrl_n_returns_to_starting_tag() -> None:
    forward = _cycle("#git:foo", key="ctrl+p")
    assert forward.mru_index == 1
    backward = _cycle(
        forward.text,
        current_index=forward.mru_index,
        key="ctrl+n",
    )
    assert backward.text == "#git:foo "
    assert backward.mru_index == 0


def test_deletes_tag_at_start_and_trailing_space() -> None:
    edit = _delete("#git:foo fix")
    assert edit.text == "fix"
    assert edit.cursor_offset == len("fix")


def test_deletes_tag_after_directive_prefix() -> None:
    edit = _delete("%i:a #git:foo fix")
    assert edit.text == "%i:a fix"


def test_deletes_trailing_tag_with_leading_space() -> None:
    edit = _delete("fix #git:foo")
    assert edit.text == "fix"
    assert edit.cursor_offset == len("fix")


def test_deletes_tag_in_the_middle_collapses_one_separator() -> None:
    edit = _delete("fix #git:foo more")
    assert edit.text == "fix more"


def test_tag_alone_on_first_line_consumes_trailing_newline() -> None:
    edit = _delete("#git:foo\nfix")
    assert edit.text == "fix"


def test_tag_after_inline_text_keeps_newline_and_drops_leading_space() -> None:
    edit = _delete("intro #git:foo\nfix")
    assert edit.text == "intro\nfix"


def test_deletes_only_first_tag() -> None:
    edit = _delete("#git:foo first\n---\n#git:baz second")
    assert edit.text == "first\n---\n#git:baz second"


def test_deletes_tag_after_frontmatter_and_directives() -> None:
    text = "---\nxprompts: {}\n---\n  %i:a %wait #git:foo Fix it"
    edit = _delete(text)
    assert edit.text == "---\nxprompts: {}\n---\n  %i:a %wait Fix it"


def test_tag_only_prompt_deletes_to_empty() -> None:
    edit = _delete("#git:foo")
    assert edit.text == ""
    assert edit.cursor_offset == 0


def test_no_tag_returns_none() -> None:
    assert _delete_or_none("fix the bug") is None


def test_blank_prompt_returns_none() -> None:
    assert _delete_or_none("   \n  ") is None


def test_tag_inside_fenced_block_returns_none() -> None:
    """Quoted tags in code blocks are not workflow refs, so deletion is a no-op."""
    text = "Fix the launcher:\n```\nsase run #git:quoted do thing\n```\n"
    assert _delete_or_none(text) is None


def test_cursor_before_deleted_span_is_unchanged() -> None:
    text = "intro #git:foo fix"
    edit = _delete(text, cursor_offset=2)
    assert edit.text == "intro fix"
    assert edit.cursor_offset == 2


def test_cursor_inside_deleted_span_snaps_to_start() -> None:
    text = "intro #git:foo fix"
    tag_start = text.index("#git:foo")
    edit = _delete(text, cursor_offset=tag_start + 3)
    assert edit.cursor_offset == tag_start


def test_cursor_after_deleted_span_shifts_by_removed_length() -> None:
    text = "#git:foo fix the bug"
    edit = _delete(text, cursor_offset=len(text))
    assert edit.text == "fix the bug"
    assert edit.cursor_offset == len("fix the bug")
