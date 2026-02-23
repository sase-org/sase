"""Tests for _strip_accept_suffixes helper."""

from sase.ace.tui.actions.hints._accept import _strip_accept_suffixes


def test_at_bang_combined() -> None:
    """@! sets both flags (reversed order)."""
    args, should_mail, skip_amend = _strip_accept_suffixes(["a", "b", "c@!"])
    assert args == ["a", "b", "c"]
    assert should_mail is True
    assert skip_amend is True


def test_at_alone_is_error() -> None:
    """@ as the only arg results in None (error)."""
    args, should_mail, skip_amend = _strip_accept_suffixes(["@"])
    assert args is None
    assert should_mail is True


def test_empty_args() -> None:
    """Empty args list returns None."""
    args, should_mail, skip_amend = _strip_accept_suffixes([])
    assert args is None
    assert should_mail is False
    assert skip_amend is False
