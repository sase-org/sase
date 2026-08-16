"""Patch project-scope query rewrite tests."""

from __future__ import annotations

from sase.ace.query.project_scope import (
    PROJECT_SCOPE_NESTED,
    project_scope_of,
    rewrite_project_scope,
)


def test_project_scope_of_reads_first_top_level_project_term() -> None:
    assert project_scope_of('"x" AND +sase') == "sase"
    assert project_scope_of("project:old AND project:new") == "old"
    assert project_scope_of('(project:nested) AND "x"') is None


def test_rewrite_project_scope_adds_and_replaces_spelling() -> None:
    assert rewrite_project_scope('"needle"', "sase") == '"needle" AND project:sase'
    assert rewrite_project_scope('project:old AND "needle"', "sase") == (
        'project:sase AND "needle"'
    )
    assert rewrite_project_scope('+old AND "needle"', "sase") == '+sase AND "needle"'


def test_rewrite_project_scope_removes_scope_and_adjacent_and() -> None:
    assert rewrite_project_scope('project:old AND "needle"', None) == '"needle"'
    assert rewrite_project_scope('"needle" AND project:old', None) == '"needle"'
    assert rewrite_project_scope('"a" AND project:old AND "b"', None) == ('"a" AND "b"')


def test_rewrite_project_scope_drops_extra_top_level_scopes() -> None:
    assert (
        rewrite_project_scope(
            'project:old AND "needle" AND +extra',
            "sase",
        )
        == 'project:sase AND "needle"'
    )


def test_rewrite_project_scope_refuses_nested_only_scope() -> None:
    assert rewrite_project_scope('(project:old OR "x")', "sase") == (
        PROJECT_SCOPE_NESTED
    )
