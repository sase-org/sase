"""Tests for repeat prompt directives."""

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_repeat_colon_arg() -> None:
    """%repeat:3 sets repeat_count=3."""
    prompt = "%repeat:3\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 3


def test_repeat_alias_r() -> None:
    """%r:5 (short alias) sets repeat_count=5."""
    prompt = "%r:5\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 5


def test_repeat_paren_arg() -> None:
    """%repeat(10) sets repeat_count=10."""
    prompt = "%repeat(10)\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 10


def test_repeat_bare_raises() -> None:
    """Bare %repeat without argument raises DirectiveError."""
    prompt = "%repeat\nDo the work"
    with pytest.raises(DirectiveError, match="requires a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_zero_raises() -> None:
    """%repeat:0 raises DirectiveError."""
    prompt = "%repeat:0\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_negative_raises() -> None:
    """%repeat:-1 raises DirectiveError."""
    prompt = "%repeat:-1\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_non_integer_raises() -> None:
    """%repeat:abc raises DirectiveError."""
    prompt = "%repeat:abc\nDo the work"
    with pytest.raises(DirectiveError, match="must be a positive integer"):
        extract_prompt_directives(prompt)


def test_repeat_one_is_valid() -> None:
    """%repeat:1 is valid (no-op, but allowed)."""
    prompt = "%repeat:1\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 1


def test_repeat_with_other_directives() -> None:
    """%repeat combined with %model and %id works."""
    prompt = "%repeat:3\n%model:opus\n%id:foo\nDo the work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do the work"
    assert directives.repeat_count == 3
    assert directives.model == "opus"
    assert directives.name == "foo"


def test_repeat_duplicate_raises() -> None:
    """Duplicate %repeat raises DirectiveError."""
    prompt = "%repeat:3\n%repeat:5\nDo the work"
    with pytest.raises(DirectiveError, match="Duplicate directive '%repeat'"):
        extract_prompt_directives(prompt)


def test_repeat_default_none() -> None:
    """Default repeat_count is None."""
    prompt = "Just a normal prompt"
    _, directives = extract_prompt_directives(prompt)
    assert directives.repeat_count is None


def test_extract_prompt_directives_preserves_repeat_for_launcher() -> None:
    """Sanity check that the directive parser stays in sync with the launcher."""
    from sase.agent.repeat_launcher import extract_repeat_and_name

    prompt = "%r:4 do X"
    _, directives = extract_prompt_directives(prompt)
    assert directives.repeat_count == 4

    launcher_count, launcher_base, _ = extract_repeat_and_name(prompt)
    assert launcher_count == directives.repeat_count
    assert launcher_base is None
