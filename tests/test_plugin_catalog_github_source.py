"""Tests for the ``gh``-backed plugin catalog source."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from sase.plugins.github_source import (
    GH_SEARCH_QUERY,
    SASE_PLUGIN_TOPIC,
    _CatalogParseError,
    _GhCommandError,
    GhNotFoundError,
    fetch_catalog_payload,
)


def _gh_present(_name: str) -> str | None:
    return "/usr/bin/gh"


def _gh_absent(_name: str) -> str | None:
    return None


def _run_returning(
    stdout: str = "",
    *,
    returncode: int = 0,
    stderr: str = "",
):
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _run


def _search_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": "sase-github",
        "full_name": "sase-org/sase-github",
        "owner": {"login": "sase-org"},
        "description": "GitHub VCS & PR workflows",
        "html_url": "https://github.com/sase-org/sase-github",
        "homepage": "https://sase.dev/plugins/github",
        "topics": ["sase--plugin", "github", "vcs"],
        "stargazers_count": 12,
        "archived": False,
        "license": {"spdx_id": "MIT"},
        "pushed_at": "2026-06-20T10:00:00Z",
        "updated_at": "2026-06-21T10:00:00Z",
    }
    item.update(overrides)
    return item


def test_fetch_uses_double_dash_topic_query() -> None:
    calls: list[list[str]] = []

    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"total_count": 0, "items": []}),
            stderr="",
        )

    payload = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)

    assert payload == []
    assert SASE_PLUGIN_TOPIC == "sase--plugin"
    assert GH_SEARCH_QUERY == "topic:sase--plugin"
    assert calls == [
        [
            "gh",
            "api",
            "--paginate",
            "-X",
            "GET",
            "search/repositories?q=topic:sase--plugin&per_page=100",
        ]
    ]


def test_fetch_parses_search_envelope_into_canonical_entry() -> None:
    stdout = json.dumps({"total_count": 1, "items": [_search_item()]})

    payload = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert len(payload) == 1
    entry = payload[0]
    assert entry["name"] == "github"  # short name strips the ``sase-`` prefix
    assert entry["repo"] == "sase-github"
    assert entry["full_name"] == "sase-org/sase-github"
    assert entry["owner"] == "sase-org"
    assert entry["description"] == "GitHub VCS & PR workflows"
    assert entry["url"] == "https://github.com/sase-org/sase-github"
    assert entry["homepage"] == "https://sase.dev/plugins/github"
    assert entry["topics"] == ["sase--plugin", "github", "vcs"]
    assert entry["stars"] == 12
    assert entry["archived"] is False
    assert entry["license"] == "MIT"
    # ``pushed_at`` is preferred over ``updated_at`` for last-updated.
    assert entry["updated_at"] == "2026-06-20T10:00:00Z"


def test_fetch_concatenates_paginated_objects() -> None:
    page1 = json.dumps({"items": [_search_item()]})
    page2 = json.dumps(
        {
            "items": [
                _search_item(
                    name="sase-telegram",
                    full_name="sase-org/sase-telegram",
                    topics=["sase--plugin"],
                )
            ]
        }
    )
    stdout = f"{page1}\n{page2}"

    payload = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert [entry["repo"] for entry in payload] == ["sase-github", "sase-telegram"]


def test_fetch_accepts_bare_array_output() -> None:
    stdout = json.dumps([_search_item()])

    payload = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert [entry["repo"] for entry in payload] == ["sase-github"]


def test_fetch_handles_missing_optional_fields() -> None:
    item = {
        "name": "acme-jira",
        "full_name": "acme-corp/acme-jira",
        "owner": {"login": "acme-corp"},
        "description": None,
        "html_url": "https://github.com/acme-corp/acme-jira",
        "homepage": None,
        "topics": ["sase--plugin"],
        "stargazers_count": 0,
        "archived": True,
        "license": None,
        "pushed_at": "2026-01-01T00:00:00Z",
    }
    stdout = json.dumps({"items": [item]})

    entry = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))[
        0
    ]

    assert entry["name"] == "acme-jira"  # no ``sase-`` prefix to strip
    assert entry["owner"] == "acme-corp"
    assert entry["description"] == ""
    assert entry["homepage"] == ""
    assert entry["license"] == ""
    assert entry["archived"] is True


def test_fetch_empty_output_returns_empty_list() -> None:
    payload = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(""))
    assert payload == []


def test_fetch_raises_when_gh_missing() -> None:
    with pytest.raises(GhNotFoundError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_absent, run_fn=_run_returning(""))
    assert "gh auth login" in str(excinfo.value)


def test_fetch_raises_on_nonzero_exit_with_detail() -> None:
    run_fn = _run_returning("", returncode=1, stderr="HTTP 401: Bad credentials")

    with pytest.raises(_GhCommandError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_present, run_fn=run_fn)
    assert "Bad credentials" in str(excinfo.value)


def test_fetch_raises_on_timeout() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=20.0)

    with pytest.raises(_GhCommandError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)
    assert "timed out" in str(excinfo.value)


def test_fetch_raises_on_os_error() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    with pytest.raises(_GhCommandError):
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)


def test_fetch_raises_on_malformed_json() -> None:
    with pytest.raises(_CatalogParseError):
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning("{not json"))
