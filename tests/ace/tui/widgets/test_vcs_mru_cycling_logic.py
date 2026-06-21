"""Pure-function tests for prompt VCS xprompt tag deletion.

Prompt ``Ctrl+N`` deletes the first real VCS workflow tag from the prompt body.
These tests pin the deletion edit produced by ``_delete_vcs_xprompt_text`` --
tag detection, separator cleanup, and cursor placement -- without involving MRU
history (prompt cycling no longer exists).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from sase.ace.tui.widgets._vcs_xprompt_delete import (
    _VcsXPromptDeleteEdit,
    _delete_vcs_xprompt_text,
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


def test_deletes_tag_at_start_and_trailing_space() -> None:
    edit = _delete("#git:foo fix")
    assert edit.text == "fix"
    assert edit.cursor_offset == len("fix")


def test_deletes_tag_after_directive_prefix() -> None:
    edit = _delete("%n:a #git:foo fix")
    assert edit.text == "%n:a fix"


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
    text = "---\nxprompts: {}\n---\n  %n:a %wait #git:foo Fix it"
    edit = _delete(text)
    assert edit.text == "---\nxprompts: {}\n---\n  %n:a %wait Fix it"


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
