"""Tests for boolean prompt directive types."""

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %plan / %approve directive tests ---
#
# %plan/%p is the canonical "auto-approve the submitted plan as a normal plan"
# directive. %approve/%a are deprecated aliases that still parse the same way.


def test_plan_bare() -> None:
    """%plan (bare) sets approve=True and strips the directive."""
    cleaned, directives = extract_prompt_directives("%plan\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_plan_alias_p() -> None:
    """%p (alias) sets approve=True."""
    cleaned, directives = extract_prompt_directives("%p\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_plan_plus() -> None:
    """%plan+ sets approve=True."""
    cleaned, directives = extract_prompt_directives("%plan+\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_plan_is_pure_normal_plan_approval() -> None:
    """%plan does not enable plan mode; it sets no tale/epic flag."""
    _, directives = extract_prompt_directives("%plan\nDo the work")
    assert directives.tale is False
    assert directives.epic is False


def test_plan_with_other_directives() -> None:
    """%plan combined with %model works."""
    cleaned, directives = extract_prompt_directives("%plan\n%model:opus\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True
    assert directives.model == "opus"


def test_plan_duplicate_raises() -> None:
    """Duplicate %plan raises DirectiveError naming the canonical directive."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%plan'"):
        extract_prompt_directives("%plan\n%plan\nDo the work")


def test_approve_is_deprecated_alias_of_plan() -> None:
    """%approve still parses to approve=True (deprecated %plan alias)."""
    cleaned, directives = extract_prompt_directives("%approve\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_short_alias_a_still_parses() -> None:
    """%a still parses to approve=True (deprecated %plan alias)."""
    cleaned, directives = extract_prompt_directives("%a\nDo the work")
    assert cleaned == "Do the work"
    assert directives.approve is True


def test_approve_and_plan_are_the_same_directive() -> None:
    """%approve then %plan collapse to one directive, so this duplicates."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%plan'"):
        extract_prompt_directives("%approve\n%plan\nDo the work")


def test_approve_default_false() -> None:
    """Default approve is False."""
    _, directives = extract_prompt_directives("Just a normal prompt")
    assert directives.approve is False


# --- %tale directive tests ---


def test_tale_bare() -> None:
    """%tale sets tale=True and strips the directive."""
    cleaned, directives = extract_prompt_directives("%tale\nWrite a plan")
    assert cleaned == "Write a plan"
    assert directives.tale is True
    assert directives.approve is False
    assert directives.epic is False


def test_tale_alias_t() -> None:
    """%t is the tale alias now (it no longer means %time)."""
    cleaned, directives = extract_prompt_directives("%t\nWrite a plan")
    assert cleaned == "Write a plan"
    assert directives.tale is True


def test_tale_plus() -> None:
    """%tale+ sets tale=True."""
    _, directives = extract_prompt_directives("%tale+\nWrite a plan")
    assert directives.tale is True


def test_tale_duplicate_raises() -> None:
    """Duplicate %tale raises DirectiveError."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%tale'"):
        extract_prompt_directives("%tale\n%tale\nDo the work")


def test_tale_default_false() -> None:
    """Default tale is False."""
    _, directives = extract_prompt_directives("Just a normal prompt")
    assert directives.tale is False


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
