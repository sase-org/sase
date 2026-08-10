"""Tests for compact and machine-readable VCS log rendering."""

from __future__ import annotations

import json

import pytest

import sase.vcs_log._render_plain as plain_mod
from sase.core.vcs_log_facade import _MergeSummary
from sase.vcs_log.models import CommitFilters, LogRepo, RepoRemoteState, VcsLogResult

from ._vcs_log_render_helpers import (
    _entry,
    _linked_tagged_result,
    _render,
    _result,
    _tagged_result,
)


def test_oneline_golden() -> None:
    assert _render(_result(), "oneline") == (
        "↑ a1b2c3d sase      fix(sdd): link store\n"
        "↓ 9f8e7d6 sase-core feat(core): parser\n"
        "● 4c5d6e7 sase      docs: notes\n"
    )


def test_oneline_marks_merges_when_present() -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "merge000",
                300,
                "Merge pull request #123 from org/feature",
                parent_ids=("parent0000", "parent1111"),
            ),
            _entry("sase", "plain000", 200, "ordinary subject"),
        ),
        warnings=(),
    )

    assert _render(result, "oneline") == (
        "● merge00 sase ◆ Merge pull request #123 from org/feature\n"
        "● plain00 sase   ordinary subject\n"
    )


def test_oneline_empty_is_blank() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    assert _render(empty, "oneline") == ""


def test_oneline_tags_suffix() -> None:
    assert _render(_tagged_result(), "oneline") == (
        "● a1b2c3d sase tagged subject [TYPE=sdd PLAN=sdd/foo.md]\n"
        "● b2c3d4e sase plain subject\n"
    )


def test_oneline_no_tags_suppresses_suffix() -> None:
    assert _render(_tagged_result(), "oneline", show_tags=False) == (
        "● a1b2c3d sase tagged subject\n● b2c3d4e sase plain subject\n"
    )


def test_json_shape_and_ordering() -> None:
    payload = json.loads(_render(_result(), "json"))
    assert list(payload.keys()) == ["commits", "query", "repos", "warnings"]
    assert [c["short_id"] for c in payload["commits"]] == [
        "a1b2c3d",
        "9f8e7d6",
        "4c5d6e7",
    ]
    # Each commit carries repo label + ids + author + email + timestamp + subject.
    first = payload["commits"][0]
    assert first == {
        "author_email": "b@x",
        "author_name": "bryan",
        "full_id": "a1b2c3d4",
        "is_merge": False,
        "merge": None,
        "parent_ids": [],
        "presence": "local_only",
        "repo": "sase",
        "sase_tags": {},
        "short_id": "a1b2c3d",
        "subject": "fix(sdd): link store",
        "timestamp": 300,
    }
    assert payload["query"] == {
        "all": False,
        "authors": [],
        "limit": 40,
        "merges": "hide",
        "reverse": False,
        "since": None,
        "until": None,
    }
    assert payload["repos"][0] == {
        "kind": "primary",
        "name": "sase",
        "path": "/p/sase",
        "remote_ref": "origin/main",
        "ahead": 1,
        "behind": 0,
        "fetched": True,
        "fetched_at": None,
    }
    assert payload["warnings"] == ["sase-telegram: no such checkout"]


def test_json_tags_shape() -> None:
    payload = json.loads(_render(_tagged_result(), "json"))

    assert payload["commits"][0]["sase_tags"] == {
        "PLAN": "sdd/foo.md",
        "TYPE": "sdd",
    }
    assert payload["commits"][1]["sase_tags"] == {}


def test_linked_tag_rendering_uses_label_and_omits_reference_definition() -> None:
    oneline = _render(_linked_tagged_result(), "oneline")
    payload = json.loads(_render(_linked_tagged_result(), "json"))
    full = _render(_linked_tagged_result(), "full")

    assert "PLAN=202607/foo.md" in oneline
    assert payload["commits"][0]["sase_tags"] == {"PLAN": "202607/foo.md"}
    assert "plan  202607/foo.md" in full
    assert "[1]: https://github.com" not in full


def test_json_no_tags_omits_sase_tags() -> None:
    payload = json.loads(_render(_tagged_result(), "json", show_tags=False))

    assert "sase_tags" not in payload["commits"][0]
    assert "sase_tags" not in payload["commits"][1]


def test_json_empty_result() -> None:
    empty = VcsLogResult(repos=(), commits=(), warnings=())
    payload = json.loads(_render(empty, "json"))
    assert payload == {
        "commits": [],
        "query": {
            "all": False,
            "authors": [],
            "limit": 40,
            "merges": "hide",
            "reverse": False,
            "since": None,
            "until": None,
        },
        "repos": [],
        "warnings": [],
    }


def test_json_reverse_and_query_filters() -> None:
    payload = json.loads(
        _render(
            _result(),
            "json",
            limit=0,
            filters=CommitFilters(since=100, until=300, authors=("bryan",)),
            reverse=True,
        )
    )

    assert [c["short_id"] for c in payload["commits"]] == [
        "4c5d6e7",
        "9f8e7d6",
        "a1b2c3d",
    ]
    assert payload["query"] == {
        "all": False,
        "authors": ["bryan"],
        "limit": 0,
        "merges": "hide",
        "reverse": True,
        "since": 100,
        "until": 300,
    }


def test_json_query_records_merge_mode() -> None:
    payload = json.loads(
        _render(_result(), "json", filters=CommitFilters(merges="only"))
    )

    assert payload["query"]["merges"] == "only"


def test_json_includes_merge_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry(
                "sase",
                "merge000",
                300,
                "Merge pull request #123 from org/feature",
                body="Add the feature title here",
                parent_ids=("parent0000", "parent1111"),
            ),
        ),
        warnings=(),
    )
    monkeypatch.setattr(
        plain_mod,
        "merge_summary",
        lambda _subject, _body: _MergeSummary(
            kind="pull_request",
            reference="123",
            source="org/feature",
            target=None,
            headline="Add the feature title here",
        ),
    )

    payload = json.loads(_render(result, "json"))

    assert payload["commits"][0]["parent_ids"] == ["parent0000", "parent1111"]
    assert payload["commits"][0]["is_merge"] is True
    assert payload["commits"][0]["merge"] == {
        "headline": "Add the feature title here",
        "kind": "pull_request",
        "reference": "123",
        "source": "org/feature",
        "target": None,
    }


@pytest.mark.parametrize("fmt", ["pretty", "full", "oneline", "json"])
def test_all_formats_trim_author_time_before_filling_final_limit(fmt: str) -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry("sase", "margin400", 400, "upper margin"),
            _entry("sase", "bound300", 300, "upper inclusive"),
            _entry("sase", "inside25", 250, "inside window"),
            _entry("sase", "bound200", 200, "lower inclusive"),
            _entry("sase", "outside1", 100, "below window"),
        ),
        warnings=(),
    )

    text = _render(
        result,
        fmt,
        limit=2,
        filters=CommitFilters(since=200, until=300),
    )

    assert "upper inclusive" in text
    assert "inside window" in text
    assert "upper margin" not in text
    assert "lower inclusive" not in text
    assert "below window" not in text


def test_json_exact_author_time_bounds_are_inclusive() -> None:
    result = VcsLogResult(
        repos=(LogRepo("sase", "/p/sase", "primary"),),
        commits=(
            _entry("sase", "above301", 301, "above"),
            _entry("sase", "upper300", 300, "upper"),
            _entry("sase", "lower200", 200, "lower"),
            _entry("sase", "below199", 199, "below"),
        ),
        warnings=(),
        resolved_filters=CommitFilters(since=200, until=300),
    )

    payload = json.loads(_render(result, "json", limit=0))

    assert [commit["subject"] for commit in payload["commits"]] == [
        "upper",
        "lower",
    ]
    assert payload["query"]["since"] == 200
    assert payload["query"]["until"] == 300


def test_json_marks_all_project_scope_with_unique_local_only_labels() -> None:
    result = VcsLogResult(
        repos=(
            LogRepo("alpha/shared", "/p/alpha-shared", "linked"),
            LogRepo("beta/shared", "/p/beta-shared", "linked"),
        ),
        commits=(
            _entry(
                "alpha/shared",
                "abc12345",
                200,
                "local provider commit",
                presence="unknown",
            ),
        ),
        warnings=(),
        remote_states=(
            RepoRemoteState("alpha/shared", None, 0, 0, False),
            RepoRemoteState("beta/shared", None, 0, 0, False),
        ),
    )

    payload = json.loads(_render(result, "json", all_projects=True))

    assert payload["query"]["all"] is True
    assert [repo["name"] for repo in payload["repos"]] == [
        "alpha/shared",
        "beta/shared",
    ]
    assert payload["commits"][0]["presence"] == "unknown"
