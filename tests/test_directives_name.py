"""Tests for name prompt directives."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


@pytest.mark.parametrize("prompt", ["%name:legacy\nDo work", "%n:legacy\nDo work"])
def test_old_name_spellings_raise_migration_error(prompt: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"renamed; use %id/%i.*%id\(<id>, clan=<clan>\)",
    ):
        extract_prompt_directives(prompt)


def test_name_bare_auto_generates() -> None:
    """Bare %id auto-generates a name via get_next_auto_name()."""
    prompt = "%id\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "a"


def test_name_bare_alias_auto_generates() -> None:
    """Bare %i auto-generates a name."""
    prompt = "%i\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="b",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"


def test_name_bare_is_not_explicit() -> None:
    """Bare %id (auto-named) leaves name_explicit=False."""
    prompt = "%id\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.name_explicit is False


def test_no_name_directive_is_not_explicit() -> None:
    """No %id directive leaves name_explicit=False."""
    _, directives = extract_prompt_directives("Do work")
    assert directives.name_explicit is False


def test_name_with_arg_is_explicit() -> None:
    """%id:foo sets name_explicit=True."""
    prompt = "%id:foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is False


def test_name_force_reuse_arg_sets_separate_flag() -> None:
    """%id:!foo keeps the actual name separate from forced reuse intent."""
    prompt = "%id:!foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is True


def test_name_paren_arg_is_explicit() -> None:
    """%id(foo) sets name_explicit=True."""
    prompt = "%id(foo)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_backtick_arg_is_explicit() -> None:
    """%id:`foo` sets name_explicit=True."""
    prompt = "%id:`foo`\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_template_colon_arg() -> None:
    """%i:foo-@ is parsed as one template argument."""
    prompt = "%i:foo-@\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "foo-@"
    assert directives.name_explicit is True
    assert directives.name_template == "foo-@"
    assert directives.name_template_base == "foo"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_template_paren_arg() -> None:
    """%id(foo-@) is parsed as a template argument."""
    _, directives = extract_prompt_directives("%id(foo-@)\nDo work")
    assert directives.name == "foo-@"
    assert directives.name_template == "foo-@"
    assert directives.name_template_base == "foo"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_template_rejects_force_reuse() -> None:
    prompt = "%id:!foo-@\nDo work"
    with pytest.raises(DirectiveError, match="forced name reuse"):
        extract_prompt_directives(prompt)


def test_name_template_bare_marker_arg() -> None:
    _, directives = extract_prompt_directives("%id:@\nDo work")
    assert directives.name == "@"
    assert directives.name_template == "@"
    assert directives.name_template_base == "@"
    assert directives.name_indexed_template is True


def test_name_template_suffix_shape_arg() -> None:
    _, directives = extract_prompt_directives("%id:@.cld\nDo work")
    assert directives.name == "@.cld"
    assert directives.name_template == "@.cld"
    assert directives.name_template_base == "cld"
    assert directives.name_indexed_template is True


def test_name_template_middle_shape_arg() -> None:
    _, directives = extract_prompt_directives("%id:research.@.final\nDo work")
    assert directives.name == "research.@.final"
    assert directives.name_template == "research.@.final"
    assert directives.name_template_base == "research.final"
    assert directives.name_indexed_template is True
