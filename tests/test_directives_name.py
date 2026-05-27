"""Tests for name prompt directives."""

from unittest.mock import patch

import pytest

from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_name_bare_auto_generates() -> None:
    """Bare %name auto-generates a name via get_next_auto_name()."""
    prompt = "%name\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "a"


def test_name_bare_alias_auto_generates() -> None:
    """Bare %n auto-generates a name."""
    prompt = "%n\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="b",
    ):
        cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "b"


def test_name_bare_is_not_explicit() -> None:
    """Bare %name (auto-named) leaves name_explicit=False."""
    prompt = "%name\nDo work"
    with patch(
        "sase.agent.names.get_next_auto_name",
        return_value="a",
    ):
        _, directives = extract_prompt_directives(prompt)
    assert directives.name_explicit is False


def test_no_name_directive_is_not_explicit() -> None:
    """No %name directive leaves name_explicit=False."""
    _, directives = extract_prompt_directives("Do work")
    assert directives.name_explicit is False


def test_name_with_arg_is_explicit() -> None:
    """%name:foo sets name_explicit=True."""
    prompt = "%name:foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is False


def test_name_force_reuse_arg_sets_separate_flag() -> None:
    """%name:!foo keeps the actual name separate from forced reuse intent."""
    prompt = "%name:!foo\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True
    assert directives.name_force_reuse is True


def test_name_paren_arg_is_explicit() -> None:
    """%name(foo) sets name_explicit=True."""
    prompt = "%name(foo)\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_backtick_arg_is_explicit() -> None:
    """%name:`foo` sets name_explicit=True."""
    prompt = "%name:`foo`\nDo work"
    _, directives = extract_prompt_directives(prompt)
    assert directives.name == "foo"
    assert directives.name_explicit is True


def test_name_indexed_template_colon_arg() -> None:
    """%n:foo-@ is parsed as one indexed-template argument."""
    prompt = "%n:foo-@\nDo work"
    cleaned, directives = extract_prompt_directives(prompt)
    assert cleaned == "Do work"
    assert directives.name == "foo-@"
    assert directives.name_explicit is True
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_indexed_template_paren_arg() -> None:
    """%name(foo-@) is parsed as an indexed-template argument."""
    _, directives = extract_prompt_directives("%name(foo-@)\nDo work")
    assert directives.name == "foo-@"
    assert directives.name_indexed_template is True
    assert directives.name_indexed_base == "foo"


def test_name_indexed_template_rejects_force_reuse() -> None:
    prompt = "%name:!foo-@\nDo work"
    with pytest.raises(DirectiveError, match="forced name reuse"):
        extract_prompt_directives(prompt)
