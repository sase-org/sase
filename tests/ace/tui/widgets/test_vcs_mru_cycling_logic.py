"""Pure-function tests for prompt VCS MRU cycling."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from sase.ace.tui.widgets._vcs_mru_cycling import (
    _VcsMruCycleEdit,
    VcsMruCycleKey,
    _cycle_vcs_mru_text,
)

_TEST_EMBEDDED_VCS_PATTERN = re.compile(
    r"(?:^|(?<=\s))#(?:gh|git|hg|cd)(?:!!|\?\?)?(?:\([^)]*\)|\+|[_:][^\s]*|)\s"
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
            return_value={"gh", "git", "hg", "cd"},
        ),
    ):
        yield
    parsing._VCS_UNDERSCORE_NORMALIZER = None
    vcs_refs._VCS_UNDERSCORE_NORMALIZER = None


def _cycle(
    text: str,
    *,
    key: VcsMruCycleKey = "ctrl+p",
    cursor_offset: int | None = None,
    current_index: int | None = None,
    mru: list[str] | None = None,
) -> _VcsMruCycleEdit:
    with _patched_vcs_parsing():
        edit = _cycle_vcs_mru_text(
            text=text,
            cursor_offset=len(text) if cursor_offset is None else cursor_offset,
            mru=mru or ["#git:foo", "#git:bar", "#git:baz"],
            key=key,
            current_index=current_index,
        )
    assert edit is not None
    return edit


def test_empty_prompt_cycles_to_directional_default() -> None:
    edit = _cycle("", key="ctrl+n")
    assert edit.text == "#git:baz "
    assert edit.cursor_offset == len("#git:baz ")
    assert edit.mru_index == 2


def test_replaces_first_existing_tag_and_preserves_body() -> None:
    edit = _cycle("#git:foo fix the bug")
    assert edit.text == "#git:bar fix the bug"
    assert edit.cursor_offset == len("#git:bar fix the bug")
    assert edit.mru_index == 1


def test_current_tag_lookup_honors_ctrl_n_direction() -> None:
    edit = _cycle("#git:bar fix the bug", key="ctrl+n")
    assert edit.text == "#git:foo fix the bug"
    assert edit.mru_index == 0


def test_current_tag_lookup_normalizes_underscore_refs() -> None:
    edit = _cycle("#gh_sase fix", mru=["#gh:sase", "#gh:other"])
    assert edit.text == "#gh:other fix"
    assert edit.mru_index == 1


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
    text = "---\nxprompts: {}\n---\n  %n:a %wait Fix it"
    edit = _cycle(text)
    assert edit.text == "---\nxprompts: {}\n---\n  %n:a %wait #git:foo Fix it"
    assert edit.start_offset == len("---\nxprompts: {}\n---\n  %n:a %wait ")


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
