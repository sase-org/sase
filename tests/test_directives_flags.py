"""Tests for boolean prompt directive types."""

import pytest

from sase.xprompt._directive_types import PromptDirectives
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %approve directive tests ---


def test_approve_bare() -> None:
    """%approve (bare) sets approve=True."""
    prompt = "%approve\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_plus() -> None:
    """%approve+ sets approve=True."""
    prompt = "%approve+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_alias() -> None:
    """%a (alias) sets approve=True."""
    prompt = "%a\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_default_false() -> None:
    """Default approve is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.approve is False


def test_approve_with_other_directives() -> None:
    """%approve combined with %model works."""
    prompt = "%approve\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.approve is True
    assert directives.model == "opus"


def test_approve_duplicate_raises() -> None:
    """Duplicate %approve raises DirectiveError."""
    prompt = "%approve\n%approve\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%approve'"):
        extract_prompt_directives(prompt)


# --- %epic directive tests ---


def test_epic_bare() -> None:
    """%epic sets epic=True and strips the directive."""
    prompt = "%epic\nWrite an epic plan"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Write an epic plan"
    assert directives.epic is True
    assert directives.approve is False


def test_epic_duplicate_raises() -> None:
    """Duplicate %epic raises DirectiveError."""
    prompt = "%epic\n%epic\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%epic'"):
        extract_prompt_directives(prompt)


def test_e_alias_still_means_edit_not_epic() -> None:
    """%e remains the edit alias; %epic has no short alias."""
    cleaned, directives = extract_prompt_directives("%e\nDo the work")
    assert cleaned == "Do the work"
    assert directives.edit is True
    assert directives.epic is False


# --- removed %plan directive ---
# The legacy manual planning directive (%plan and its %p alias) was removed.
# It is now treated like any other unknown %name token: left in the prompt and
# never parsed into metadata.


def test_removed_plan_directive_is_unknown_text() -> None:
    """%plan is no longer a directive; it stays in the prompt verbatim."""
    prompt = "%plan\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_removed_plan_alias_is_unknown_text() -> None:
    """%p is no longer the plan alias; it stays in the prompt verbatim."""
    prompt = "%p\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


def test_repeated_removed_plan_directive_does_not_raise() -> None:
    """An unknown %plan token no longer triggers duplicate-directive errors."""
    prompt = "%plan\n%plan\nFix the bug"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives == PromptDirectives()


# --- %hide directive tests ---


def test_hide_bare() -> None:
    """%hide (bare) sets hide=True."""
    prompt = "%hide\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_plus() -> None:
    """%hide+ sets hide=True."""
    prompt = "%hide+\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_alias() -> None:
    """%h (alias) sets hide=True."""
    prompt = "%h\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True


def test_hide_default_false() -> None:
    """Default hide is False."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.hide is False


def test_hide_with_other_directives() -> None:
    """%hide combined with %model works."""
    prompt = "%hide\n%model:opus\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.hide is True
    assert directives.model == "opus"


def test_hide_duplicate_raises() -> None:
    """Duplicate %hide raises DirectiveError."""
    prompt = "%hide\n%hide\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%hide'"):
        extract_prompt_directives(prompt)


# --- %edit directive tests ---


def test_edit_bare() -> None:
    """%edit (bare) sets edit=True."""
    prompt = "%edit\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.edit is True


def test_edit_alias() -> None:
    """%e (alias) sets edit=True."""
    prompt = "%e\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.edit is True


def test_edit_inside_fenced_block_ignored() -> None:
    """%edit inside triple backticks is not extracted."""
    prompt = "```\n%edit\n```"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.edit is False


def test_edit_duplicate_raises() -> None:
    """Duplicate %edit raises DirectiveError."""
    prompt = "%edit\n%edit\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%edit'"):
        extract_prompt_directives(prompt)
