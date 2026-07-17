"""Tests for boolean and auto-approval prompt directive types."""

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


# --- %auto directive tests ---


def test_auto_bare_defaults_to_plan() -> None:
    """%auto (bare) defaults to normal-plan auto-approval."""
    cleaned, directives = extract_prompt_directives("%auto\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_mode == "plan"


def test_auto_alias_a_defaults_to_plan() -> None:
    """%a is the advertised alias for %auto."""
    cleaned, directives = extract_prompt_directives("%a\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_mode == "plan"


def test_auto_plus_defaults_to_plan() -> None:
    """%auto+ defaults to normal-plan auto-approval."""
    cleaned, directives = extract_prompt_directives("%auto+\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_mode == "plan"


def test_auto_plan_explicit() -> None:
    """%auto:plan selects normal-plan auto-approval."""
    cleaned, directives = extract_prompt_directives("%auto:plan\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_mode == "plan"


def test_auto_tale() -> None:
    """%auto:tale selects tale auto-approval."""
    cleaned, directives = extract_prompt_directives("%auto:tale\nWrite a plan")
    assert cleaned == "Write a plan"
    assert directives.auto_mode == "tale"


def test_auto_epic() -> None:
    """%auto:epic selects epic auto-approval."""
    prompt = "%auto:epic\nWrite an epic plan"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Write an epic plan"
    assert directives.auto_mode == "epic"


def test_auto_with_other_directives() -> None:
    """%auto combined with %model works."""
    cleaned, directives = extract_prompt_directives("%auto\n%model:opus\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_mode == "plan"
    assert directives.model == "opus"


def test_auto_duplicate_raises() -> None:
    """Duplicate %auto raises DirectiveError naming the canonical directive."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%auto'"):
        extract_prompt_directives("%auto\n%a\nDo the work")


def test_auto_argument_is_retained_for_adapter_validation() -> None:
    """The parser retains opaque auto arguments for the eventual gate adapter."""
    cleaned, directives = extract_prompt_directives("%auto:foo\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_enabled is True
    assert directives.auto_argument == "foo"
    assert directives.auto_mode == "foo"


def test_auto_default_none() -> None:
    """Default auto_mode is None."""
    _, directives = extract_prompt_directives("Just a normal prompt")
    assert directives.auto_mode is None


@pytest.mark.parametrize(
    "token",
    ["%plan", "%p", "%plan+", "%approve", "%tale", "%tale+", "%epic"],
)
def test_removed_auto_approval_directives_are_unknown(token: str) -> None:
    """Removed auto-approval directive names stay literal in the prompt."""
    prompt = f"{token}\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == prompt
    assert directives.auto_mode is None


def test_e_alias_resolves_to_effort_not_removed_edit() -> None:
    """%e is now the %effort alias, so bare %e asks for a level (not %edit)."""
    with pytest.raises(DirectiveError, match="requires a level argument"):
        extract_prompt_directives("%e\nDo the work")


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


# --- removed %edit directive (now the editor ` @` review marker) ---


def test_edit_directive_removed_raises_migration_hint() -> None:
    """%edit raises a migration hint pointing at the editor ` @` review marker."""
    with pytest.raises(DirectiveError, match=r"%edit.*has been removed.* @"):
        extract_prompt_directives("%edit\nDo the work")


def test_edit_alias_e_no_longer_maps_to_edit() -> None:
    """%e is the %effort alias now, so %e:<level> sets effort instead of %edit."""
    _, directives = extract_prompt_directives("%e:high\nDo the work")
    assert directives.reasoning_effort == "high"


def test_edit_inside_fenced_block_ignored() -> None:
    """%edit inside triple backticks is protected and never reaches the parser."""
    prompt = "```\n%edit\n```"
    cleaned, _ = extract_prompt_directives(prompt)
    assert cleaned == prompt
