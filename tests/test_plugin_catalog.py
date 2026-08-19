"""Tests for plugin catalog load orchestration and the public model."""

from __future__ import annotations

from typing import Any

import pytest

from sase.plugins.cache import CachedCatalog
from sase.plugins.catalog import (
    PluginCatalog,
    PluginCatalogEntry,
    PluginCatalogError,
    SASE_PLUGIN_ORG,
    find_plugin,
    load_plugin_catalog,
    suggest_plugins,
)
from sase.plugins.github_source import (
    GH_SEARCH_QUERY,
    CatalogFetchResult,
    GhCommandError,
    GhNotFoundError,
)
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.inventory import ENTRY_POINT_GROUPS

OLD_GH_SEARCH_QUERY = "topic:sase-plugin"


def test_artifact_provider_entry_point_groups_are_in_inventory() -> None:
    assert "sase_artifact_refs" in ENTRY_POINT_GROUPS
    assert "sase_file_hooks" in ENTRY_POINT_GROUPS


def _payload(
    name: str,
    owner: str,
    *,
    repo: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    if repo is None:
        repo = f"sase-{name}" if owner == SASE_PLUGIN_ORG else name
    entry: dict[str, Any] = {
        "name": name,
        "repo": repo,
        "full_name": f"{owner}/{repo}",
        "owner": owner,
        "description": "",
        "url": "",
        "homepage": "",
        "topics": ["sase--plugin"],
        "stars": 0,
        "archived": False,
        "license": "",
        "updated_at": "",
    }
    entry.update(overrides)
    return entry


def _noop_write(*_args: Any, **_kwargs: Any) -> None:
    return None


def _load(
    payload: list[dict[str, Any]],
    *,
    refresh: bool = True,
    cached: CachedCatalog | None = None,
    index: dict[str, InstalledInfo] | None = None,
    now: float = 1000.0,
    fetch_fn: Any = None,
    write_fn: Any = None,
) -> PluginCatalog:
    return load_plugin_catalog(
        refresh=refresh,
        now=now,
        fetch_fn=fetch_fn or (lambda: payload),
        read_cache_fn=lambda: cached,
        write_cache_fn=write_fn or _noop_write,
        installed_index_fn=lambda: index or {},
    )


def test_classification_builtin_vs_community_and_ordering() -> None:
    payload = [
        _payload("acme-jira", "acme-corp", repo="acme-jira"),
        _payload("github", "sase-org"),
    ]

    catalog = _load(payload)

    kinds = {entry.name: entry.kind for entry in catalog.entries}
    assert kinds["github"] == "builtin"
    assert kinds["acme-jira"] == "community"
    # Built-in section is rendered first; community second.
    assert [entry.name for entry in catalog.entries] == ["github", "acme-jira"]
    assert [entry.name for entry in catalog.builtin_entries] == ["github"]
    assert [entry.name for entry in catalog.community_entries] == ["acme-jira"]


def test_classification_is_case_insensitive_on_owner() -> None:
    catalog = _load([_payload("github", "SASE-Org", repo="sase-github")])
    assert catalog.entries[0].kind == "builtin"


def test_cache_hit_does_not_touch_the_network() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )

    def _explode() -> list[dict[str, Any]]:
        raise AssertionError("cache hit must not fetch")

    catalog = _load([], refresh=False, cached=cached, fetch_fn=_explode)

    assert catalog.from_cache is True
    assert catalog.fetched_at == 500.0
    assert [entry.name for entry in catalog.entries] == ["github"]


def test_offline_uses_cache_without_fetching() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )

    def _explode() -> list[dict[str, Any]]:
        raise AssertionError("offline mode must not fetch")

    catalog = load_plugin_catalog(
        refresh=True,
        offline=True,
        now=1000.0,
        fetch_fn=_explode,
        read_cache_fn=lambda: cached,
        write_cache_fn=_noop_write,
        installed_index_fn=lambda: {},
    )

    assert catalog.from_cache is True
    assert [entry.name for entry in catalog.entries] == ["github"]


def test_offline_without_cache_raises() -> None:
    with pytest.raises(PluginCatalogError, match="offline mode"):
        load_plugin_catalog(
            offline=True,
            fetch_fn=lambda: [_payload("github", "sase-org")],
            read_cache_fn=lambda: None,
            write_cache_fn=_noop_write,
            installed_index_fn=lambda: {},
        )


def test_first_run_without_cache_fetches_and_writes() -> None:
    writes: list[tuple[Any, ...]] = []

    def _write(payload: Any, *, fetched_at: float, query: str) -> None:
        writes.append((payload, fetched_at, query))

    catalog = _load(
        [_payload("github", "sase-org")],
        refresh=False,
        cached=None,
        write_fn=_write,
    )

    assert catalog.from_cache is False
    assert catalog.fetched_at == 1000.0
    assert writes and writes[0][1] == 1000.0
    assert writes[0][2] == GH_SEARCH_QUERY


def test_old_query_cache_fetches_on_online_load() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=OLD_GH_SEARCH_QUERY,
        entries=(_payload("stale", "sase-org"),),
    )
    writes: list[tuple[Any, ...]] = []

    def _write(payload: Any, *, fetched_at: float, query: str) -> None:
        writes.append((payload, fetched_at, query))

    catalog = _load(
        [_payload("github", "sase-org")],
        refresh=False,
        cached=cached,
        write_fn=_write,
    )

    assert catalog.from_cache is False
    assert [entry.name for entry in catalog.entries] == ["github"]
    assert writes and writes[0][2] == GH_SEARCH_QUERY


def test_refresh_fetches_even_with_cache_present() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("stale", "sase-org"),),
    )

    catalog = _load([_payload("github", "sase-org")], refresh=True, cached=cached)

    assert catalog.from_cache is False
    assert catalog.fetched_at == 1000.0
    assert [entry.name for entry in catalog.entries] == ["github"]


def test_merges_installed_info_onto_entries() -> None:
    index = {
        "sase-github": InstalledInfo(
            installed=True,
            version="0.4.1",
            entry_point_groups=("sase_vcs", "sase_workspace"),
        )
    }
    payload = [
        _payload("github", "sase-org", repo="sase-github"),
        _payload("telegram", "sase-org", repo="sase-telegram"),
    ]

    catalog = _load(payload, index=index)
    by_name = {entry.name: entry for entry in catalog.entries}

    assert by_name["github"].installed.installed is True
    assert by_name["github"].installed.version == "0.4.1"
    assert by_name["github"].installed.entry_point_groups == (
        "sase_vcs",
        "sase_workspace",
    )
    assert by_name["telegram"].installed.installed is False
    assert catalog.installed_count == 1


def test_updates_available_counts_installed_index_updates() -> None:
    entry = PluginCatalog(
        fetched_at=1000.0,
        entries=(
            PluginCatalogEntry(
                name="github",
                repo="sase-github",
                full_name="sase-org/sase-github",
                owner="sase-org",
                description="",
                url="",
                homepage="",
                topics=(),
                stars=0,
                archived=False,
                license="",
                updated_at="",
                installed=InstalledInfo(installed=True, version="0.4.1"),
                latest=LatestInfo(checked=True, version="0.5.0", source="index"),
            ),
        ),
        from_cache=True,
        stale=False,
    )

    assert entry.entries[0].update_available is True
    assert entry.updates_available == 1


def test_updates_available_counts_installed_editable_dev_updates() -> None:
    catalog = PluginCatalog(
        fetched_at=1000.0,
        entries=(
            PluginCatalogEntry(
                name="github",
                repo="sase-github",
                full_name="sase-org/sase-github",
                owner="sase-org",
                description="",
                url="",
                homepage="",
                topics=(),
                stars=0,
                archived=False,
                license="",
                updated_at="",
                installed=InstalledInfo(installed=True, version="0.4.1"),
                latest=LatestInfo(
                    checked=True,
                    version="0.4.1+2.gabcdef123",
                    source="editable",
                    update_available=True,
                    state="update_available",
                ),
            ),
        ),
        from_cache=True,
        stale=False,
    )

    assert catalog.entries[0].update_available is True
    assert catalog.updates_available == 1


def test_fetch_result_warnings_are_copied_onto_the_catalog() -> None:
    fetched = CatalogFetchResult(
        entries=[_payload("github", "sase-org")],
        total_count=1001,
        incomplete_results=True,
        truncated=True,
        warnings=("plugin catalog is truncated: GitHub's 1000-result search cap",),
    )

    catalog = _load([], refresh=True, fetch_fn=lambda: fetched)

    assert [entry.name for entry in catalog.entries] == ["github"]
    assert catalog.warnings == fetched.warnings


def test_gh_command_error_falls_back_to_stale_cache_with_warning() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )

    def _fail() -> list[dict[str, Any]]:
        raise GhCommandError("HTTP 401: Bad credentials")

    catalog = _load([], refresh=True, cached=cached, fetch_fn=_fail)

    assert catalog.from_cache is True
    assert catalog.fetched_at == 500.0
    assert any("stale" in warning.lower() for warning in catalog.warnings)


def test_old_query_cache_is_not_refresh_failure_fallback() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=OLD_GH_SEARCH_QUERY,
        entries=(_payload("stale", "sase-org"),),
    )

    def _fail() -> list[dict[str, Any]]:
        raise GhCommandError("HTTP 401: Bad credentials")

    with pytest.raises(GhCommandError):
        _load([], refresh=True, cached=cached, fetch_fn=_fail)


def test_gh_command_error_without_cache_raises() -> None:
    def _fail() -> list[dict[str, Any]]:
        raise GhCommandError("boom")

    with pytest.raises(GhCommandError):
        _load([], refresh=True, cached=None, fetch_fn=_fail)


def test_gh_not_found_is_hard_error_even_with_cache() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )

    def _fail() -> list[dict[str, Any]]:
        raise GhNotFoundError()

    with pytest.raises(GhNotFoundError):
        _load([], refresh=True, cached=cached, fetch_fn=_fail)


def test_stale_flag_set_when_cache_old() -> None:
    cached = CachedCatalog(
        fetched_at=0.0,
        query=GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )
    catalog = _load(
        [],
        refresh=False,
        cached=cached,
        now=60 * 60 * 24 * 30,  # 30 days later
    )
    assert catalog.stale is True
    assert catalog.age_seconds(now=60 * 60 * 24 * 30) == 60 * 60 * 24 * 30


def test_offline_old_query_cache_raises_refresh_online_message() -> None:
    cached = CachedCatalog(
        fetched_at=500.0,
        query=OLD_GH_SEARCH_QUERY,
        entries=(_payload("github", "sase-org"),),
    )

    with pytest.raises(PluginCatalogError) as excinfo:
        load_plugin_catalog(
            offline=True,
            fetch_fn=lambda: [_payload("github", "sase-org")],
            read_cache_fn=lambda: cached,
            write_cache_fn=_noop_write,
            installed_index_fn=lambda: {},
        )

    message = str(excinfo.value)
    assert "incompatible" in message
    assert "sase plugin list --refresh" in message
    assert "online" in message


def test_find_plugin_matches_name_repo_and_full_name() -> None:
    catalog = _load([_payload("github", "sase-org")])

    assert find_plugin(catalog, "github").name == "github"  # type: ignore[union-attr]
    assert find_plugin(catalog, "sase-github").name == "github"  # type: ignore[union-attr]
    assert (
        find_plugin(catalog, "sase-org/sase-github").name == "github"  # type: ignore[union-attr]
    )
    assert find_plugin(catalog, "GITHUB").name == "github"  # type: ignore[union-attr]
    assert find_plugin(catalog, "nonexistent") is None
    assert find_plugin(catalog, "   ") is None


def test_suggest_plugins_ranks_close_matches() -> None:
    catalog = _load(
        [
            _payload("github", "sase-org"),
            _payload("telegram", "sase-org"),
            _payload("acme-jira", "acme-corp", repo="acme-jira"),
        ]
    )

    suggestions = suggest_plugins(catalog, "gthub")

    assert suggestions
    assert suggestions[0].name == "github"


def test_suggest_plugins_empty_query_returns_nothing() -> None:
    catalog = _load([_payload("github", "sase-org")])
    assert suggest_plugins(catalog, "") == ()
