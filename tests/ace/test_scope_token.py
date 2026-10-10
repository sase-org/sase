"""Unit coverage for host-owned ``in:`` token helpers."""

from __future__ import annotations

import pytest

from sase.ace.query.scope_token import (
    HOST_SCOPE_VALUES,
    ScopeTokenError,
    extract_scope,
    inbox_membership_query,
)


def test_extract_scope_absent_returns_original_query() -> None:
    query = "  status:FAILED  since:24h  "

    remainder, scope = extract_scope(query)

    assert remainder == query
    assert scope is None


@pytest.mark.parametrize(
    ("query", "remainder", "scope"),
    [
        ("in:archive", "", "archive"),
        ("IN:ARCHIVE", "", "archive"),
        ("in:inbox", "", "inbox"),
        ('in:"archive"', "", "archive"),
        ("status:FAILED in:archive since:24h", "status:FAILED since:24h", "archive"),
        ("in:archive AND status:FAILED", "status:FAILED", "archive"),
        ("status:FAILED AND in:archive", "status:FAILED", "archive"),
        ("in:archive status:FAILED", "status:FAILED", "archive"),
    ],
)
def test_extract_scope_strips_token_and_canonicalizes_value(
    query: str,
    remainder: str,
    scope: str,
) -> None:
    assert extract_scope(query) == (remainder, scope)


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("-in:archive", "may not be negated"),
        ("NOT in:archive", "inside NOT"),
        ("!in:archive", "inside NOT"),
        ("in:", "requires a value"),
        ("in:bogus", "must be 'inbox' or 'archive'"),
        ("in:history", "must be 'inbox' or 'archive'"),
        ("in:archive in:inbox", "only appear once"),
        ("(in:archive)", "inside parentheses"),
        ("status:FAILED AND (in:archive)", "inside parentheses"),
        ("in:archive OR status:FAILED", "inside OR"),
        ("status:FAILED OR in:archive", "inside OR"),
    ],
)
def test_extract_scope_rejects_invalid_tokens(query: str, message: str) -> None:
    with pytest.raises(ScopeTokenError, match=message):
        extract_scope(query)


def test_extract_scope_allows_or_inside_parentheses() -> None:
    remainder, scope = extract_scope("in:archive AND (status:FAILED OR status:DONE)")
    assert scope == "archive"
    assert remainder == "(status:FAILED OR status:DONE)"


def test_extract_scope_rejects_unterminated_quote() -> None:
    with pytest.raises(ScopeTokenError, match="Unterminated double quote"):
        extract_scope('"in:archive')


def test_quoted_in_token_is_not_scope() -> None:
    query = '"in:archive"'
    remainder, scope = extract_scope(query)
    assert remainder == query
    assert scope is None


def test_scope_hints_use_the_offending_field_name() -> None:
    with pytest.raises(
        ScopeTokenError,
        match="restorable: is an Archive field · add in:archive or press ,a",
    ):
        inbox_membership_query("restorable:true")
    with pytest.raises(
        ScopeTokenError,
        match="unread: is an Inbox field · remove in:archive or press ,a",
    ):
        inbox_membership_query("in:archive unread:true")


def test_inbox_membership_query_hints_archive_fields_without_in_archive() -> None:
    with pytest.raises(ScopeTokenError, match="Archive field"):
        inbox_membership_query("restorable:true")
    with pytest.raises(ScopeTokenError, match="Archive field"):
        inbox_membership_query("in:inbox outcome:failed")


def test_inbox_membership_query_hints_inbox_fields_with_in_archive() -> None:
    with pytest.raises(ScopeTokenError, match="Inbox field"):
        inbox_membership_query("in:archive unread:true")


def test_inbox_membership_query_strips_archive_fields_for_inbox_eval() -> None:
    remainder, scope = inbox_membership_query("in:archive restorable:true")
    assert scope == "archive"
    assert remainder == ""

    remainder, scope = inbox_membership_query(
        "in:archive restorable:true status:FAILED"
    )
    assert scope == "archive"
    assert remainder == "status:FAILED"


def test_in_archive_alone_is_valid_inbox_membership() -> None:
    remainder, scope = inbox_membership_query("in:archive")
    assert scope == "archive"
    assert remainder == ""


def test_host_scope_completion_values() -> None:
    assert HOST_SCOPE_VALUES == ("inbox", "archive")
