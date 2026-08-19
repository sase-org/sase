"""Tests for the ``gh``-backed plugin catalog source."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from sase.plugins.github_source import (
    GH_SEARCH_PER_PAGE,
    GH_SEARCH_QUERY,
    GH_SEARCH_RESULT_CAP,
    GH_TIMEOUT_SECONDS,
    SASE_PLUGIN_TOPIC,
    CatalogFetchResult,
    CatalogParseError,
    GhCommandError,
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
        "created_at": "2026-01-15T10:00:00Z",
        "pushed_at": "2026-06-20T10:00:00Z",
        "updated_at": "2026-06-21T10:00:00Z",
    }
    item.update(overrides)
    return item


def _parse_endpoint(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(
        endpoint if "://" in endpoint else f"https://api.github.com/{endpoint}"
    )
    params = parse_qs(parsed.query)
    query = params.get("q", [""])[0]
    try:
        page = int(params.get("page", ["1"])[0])
    except ValueError:
        page = 1
    return query, page


def _corpus_item(index: int, **overrides: Any) -> dict[str, Any]:
    name = f"sase-plugin{index:04d}"
    created = date(2018, 1, 1).toordinal() + index
    created_date = date.fromordinal(created)
    item = _search_item(
        name=name,
        full_name=f"community-lab/{name}",
        owner={"login": "community-lab"},
        description="synthetic catalog row",
        html_url=f"https://github.com/community-lab/{name}",
        homepage="",
        topics=["sase--plugin"],
        stargazers_count=index,
        created_at=f"{created_date.isoformat()}T00:00:00Z",
        pushed_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )
    item.update(overrides)
    return item


def _item_matches_query(item: dict[str, Any], query: str) -> bool:
    if "topic:sase--plugin" in query and "sase--plugin" not in (
        item.get("topics") or []
    ):
        return False
    stars = item.get("stargazers_count", 0)
    if isinstance(stars, bool) or not isinstance(stars, int):
        stars = 0
    if not _stars_match(stars, query):
        return False
    created = _item_created(item)
    return _created_match(created, query)


def _stars_match(stars: int, query: str) -> bool:
    marker = "stars:"
    if marker not in query:
        return True
    token = next(part for part in query.split() if part.startswith(marker))
    spec = token[len(marker) :]
    if ".." in spec:
        lo_s, hi_s = spec.split("..", 1)
        return int(lo_s) <= stars <= int(hi_s)
    if spec.startswith(">="):
        return stars >= int(spec[2:])
    if spec.startswith("<="):
        return stars <= int(spec[2:])
    if spec.startswith(">"):
        return stars > int(spec[1:])
    if spec.startswith("<"):
        return stars < int(spec[1:])
    return stars == int(spec)


def _item_created(item: dict[str, Any]) -> date:
    raw = item.get("created_at")
    if isinstance(raw, str) and len(raw) >= 10:
        return date.fromisoformat(raw[:10])
    return date(2026, 6, 1)


def _created_match(created: date, query: str) -> bool:
    marker = "created:"
    if marker not in query:
        return True
    token = next(part for part in query.split() if part.startswith(marker))
    spec = token[len(marker) :]
    if ".." in spec:
        lo_s, hi_s = spec.split("..", 1)
        return date.fromisoformat(lo_s) <= created <= date.fromisoformat(hi_s)
    if spec.startswith(">="):
        return created >= date.fromisoformat(spec[2:])
    if spec.startswith("<="):
        return created <= date.fromisoformat(spec[2:])
    if spec.startswith(">"):
        return created > date.fromisoformat(spec[1:])
    if spec.startswith("<"):
        return created < date.fromisoformat(spec[1:])
    return created == date.fromisoformat(spec)


def _corpus_run_fn(items: list[dict[str, Any]]):
    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        query, page = _parse_endpoint(args[-1])
        matched = [item for item in items if _item_matches_query(item, query)]
        if page > GH_SEARCH_RESULT_CAP // GH_SEARCH_PER_PAGE:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="Only the first 1000 search results are available",
            )
        start = (page - 1) * GH_SEARCH_PER_PAGE
        page_items = matched[:GH_SEARCH_RESULT_CAP][start : start + GH_SEARCH_PER_PAGE]
        body = json.dumps(
            {
                "total_count": len(matched),
                "incomplete_results": False,
                "items": page_items,
            }
        )
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=body, stderr=""
        )

    return _run


def test_fetch_uses_double_dash_topic_query() -> None:
    calls: list[list[str]] = []

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs["timeout"] == GH_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"total_count": 0, "items": []}),
            stderr="",
        )

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)

    assert result.entries == []
    assert result.total_count == 0
    assert result.warnings == ()
    assert SASE_PLUGIN_TOPIC == "sase--plugin"
    assert GH_SEARCH_QUERY == "topic:sase--plugin"
    assert calls == [
        [
            "gh",
            "api",
            "-X",
            "GET",
            "search/repositories?q=topic:sase--plugin&per_page=100&page=1",
        ]
    ]


def test_fetch_parses_search_envelope_into_canonical_entry() -> None:
    stdout = json.dumps(
        {
            "total_count": 1,
            "incomplete_results": False,
            "items": [_search_item()],
        }
    )

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert len(result.entries) == 1
    assert result.total_count == 1
    assert result.incomplete_results is False
    entry = result.entries[0]
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


def test_fetch_pages_explicitly_instead_of_paginate() -> None:
    items = [_corpus_item(index) for index in range(250)]
    calls: list[tuple[str, int]] = []

    inner = _corpus_run_fn(items)

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == GH_TIMEOUT_SECONDS
        calls.append(_parse_endpoint(args[-1]))
        assert "--paginate" not in args
        return inner(args, **kwargs)

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)

    assert [entry["repo"] for entry in result.entries] == [
        f"sase-plugin{index:04d}" for index in range(250)
    ]
    assert calls == [
        ("topic:sase--plugin", 1),
        ("topic:sase--plugin", 2),
        ("topic:sase--plugin", 3),
    ]


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

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert [entry["repo"] for entry in result.entries] == [
        "sase-github",
        "sase-telegram",
    ]


def test_fetch_accepts_bare_array_output() -> None:
    stdout = json.dumps([_search_item()])

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert [entry["repo"] for entry in result.entries] == ["sase-github"]


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

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))
    entry = result.entries[0]

    assert entry["name"] == "acme-jira"  # no ``sase-`` prefix to strip
    assert entry["owner"] == "acme-corp"
    assert entry["description"] == ""
    assert entry["homepage"] == ""
    assert entry["license"] == ""
    assert entry["archived"] is True


def test_fetch_empty_output_returns_empty_list() -> None:
    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(""))
    assert result.entries == []
    assert result.warnings == ()


def test_fetch_raises_when_gh_missing() -> None:
    with pytest.raises(GhNotFoundError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_absent, run_fn=_run_returning(""))
    assert "gh auth login" in str(excinfo.value)


def test_fetch_raises_on_nonzero_exit_with_detail() -> None:
    run_fn = _run_returning("", returncode=1, stderr="HTTP 401: Bad credentials")

    with pytest.raises(GhCommandError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_present, run_fn=run_fn)
    assert "Bad credentials" in str(excinfo.value)


def test_fetch_raises_on_timeout() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=20.0)

    with pytest.raises(GhCommandError) as excinfo:
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)
    assert "timed out" in str(excinfo.value)


def test_later_page_timeout_returns_partial_result_with_warning() -> None:
    calls = 0

    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        _query, page = _parse_endpoint(args[-1])
        if page > 1:
            raise subprocess.TimeoutExpired(cmd="gh", timeout=20.0)
        items = [_corpus_item(index) for index in range(GH_SEARCH_PER_PAGE)]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "total_count": 250,
                    "incomplete_results": False,
                    "items": items,
                }
            ),
            stderr="",
        )

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)

    assert len(result.entries) == GH_SEARCH_PER_PAGE
    assert calls == 2
    assert any("incomplete" in warning for warning in result.warnings)
    assert any("failed" in warning for warning in result.warnings)


def test_fetch_raises_on_os_error() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    with pytest.raises(GhCommandError):
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run)


def test_fetch_raises_on_malformed_json() -> None:
    with pytest.raises(CatalogParseError):
        fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning("{not json"))


def test_fetch_warns_when_incomplete_results() -> None:
    stdout = json.dumps(
        {
            "total_count": 1,
            "incomplete_results": True,
            "items": [_search_item()],
        }
    )

    result = fetch_catalog_payload(which_fn=_gh_present, run_fn=_run_returning(stdout))

    assert len(result.entries) == 1
    assert result.incomplete_results is True
    assert any("incomplete" in warning for warning in result.warnings)


def test_fetch_shards_past_github_search_cap() -> None:
    items = [_corpus_item(index) for index in range(1500)]
    queries: list[str] = []

    inner = _corpus_run_fn(items)

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        query, _page = _parse_endpoint(args[-1])
        queries.append(query)
        return inner(args, **kwargs)

    result = fetch_catalog_payload(
        which_fn=_gh_present,
        run_fn=_run,
        today=date(2026, 8, 18),
    )

    assert len(result.entries) == 1500
    assert result.total_count == 1500
    assert result.truncated is False
    assert result.warnings == ()
    assert any("stars:" in query for query in queries)
    names = {entry["full_name"] for entry in result.entries}
    assert len(names) == 1500


def test_fetch_dedupes_sharded_results_by_full_name() -> None:
    shared = _corpus_item(0, stargazers_count=0)
    items = [
        shared,
        _corpus_item(1, stargazers_count=0, created_at="2019-06-01T00:00:00Z"),
    ]

    # Force the over-cap path with a lying total_count, then serve the same
    # two rows from every shard so union-by-full_name has work to do.
    def _run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        query, page = _parse_endpoint(args[-1])
        if query == GH_SEARCH_QUERY and page == 1:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "total_count": GH_SEARCH_RESULT_CAP + 1,
                        "incomplete_results": False,
                        "items": items,
                    }
                ),
                stderr="",
            )
        matched = [item for item in items if _item_matches_query(item, query)]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "total_count": len(matched),
                    "incomplete_results": False,
                    "items": matched,
                }
            ),
            stderr="",
        )

    result = fetch_catalog_payload(
        which_fn=_gh_present,
        run_fn=_run,
        today=date(2026, 8, 18),
    )

    assert [entry["full_name"] for entry in result.entries] == [
        item["full_name"] for item in items
    ]


def test_fetch_warns_when_an_unsplittable_shard_still_hits_the_cap() -> None:
    created = "2026-06-01T00:00:00Z"
    items = [
        _corpus_item(index, stargazers_count=0, created_at=created)
        for index in range(GH_SEARCH_RESULT_CAP + 1)
    ]

    result = fetch_catalog_payload(
        which_fn=_gh_present,
        run_fn=_corpus_run_fn(items),
        today=date(2026, 8, 18),
    )

    assert len(result.entries) == GH_SEARCH_RESULT_CAP
    assert result.truncated is True
    assert any("truncated" in warning for warning in result.warnings)
    assert any("1000" in warning for warning in result.warnings)


def test_catalog_fetch_result_is_the_public_return_type() -> None:
    result = fetch_catalog_payload(
        which_fn=_gh_present,
        run_fn=_run_returning(json.dumps({"total_count": 0, "items": []})),
    )
    assert isinstance(result, CatalogFetchResult)
