"""Tests for latest-version lookup, caching, and catalog enrichment."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import enrich_with_latest, installed_source, is_newer
from sase.plugins.latest_cache import (
    CachedLatest,
    is_fresh,
    read_cache,
    write_cache,
)
from sase.plugins.pypi_source import fetch_latest_version


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _Distribution:
    def __init__(self, direct_url: str | None) -> None:
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self._direct_url
        return None


def _entry(
    name: str,
    *,
    installed: bool = False,
    version: str | None = None,
) -> PluginCatalogEntry:
    return PluginCatalogEntry(
        name=name,
        repo=f"sase-{name}",
        full_name=f"sase-org/sase-{name}",
        owner="sase-org",
        description="",
        url="",
        homepage="",
        topics=(),
        stars=0,
        archived=False,
        license="",
        updated_at="",
        installed=InstalledInfo(installed=installed, version=version),
    )


def _catalog(*entries: PluginCatalogEntry) -> PluginCatalog:
    return PluginCatalog(
        fetched_at=1000.0,
        entries=entries,
        from_cache=True,
        stale=False,
    )


def test_fetch_latest_version_parses_info_version() -> None:
    seen: list[tuple[str, float]] = []

    def _urlopen(request: Any, *, timeout: float) -> _Response:
        seen.append((request.full_url, timeout))
        return _Response(b'{"info": {"version": "0.5.0"}}')

    assert fetch_latest_version("sase-github", urlopen_fn=_urlopen) == "0.5.0"
    assert seen == [("https://pypi.org/pypi/sase-github/json", 2.0)]


def test_fetch_latest_version_returns_none_on_404_or_bad_json() -> None:
    def _not_found(_request: Any, *, timeout: float) -> _Response:
        raise urllib.error.HTTPError("url", 404, "missing", {}, None)

    def _bad_json(_request: Any, *, timeout: float) -> _Response:
        return _Response(b"not json")

    assert fetch_latest_version("sase-missing", urlopen_fn=_not_found) is None
    assert fetch_latest_version("sase-bad", urlopen_fn=_bad_json) is None


def test_latest_cache_round_trip_and_schema_guard(tmp_path: Path) -> None:
    path = tmp_path / "latest_cache.json"
    write_cache(
        {"sase-github": CachedLatest(version="0.5.0", fetched_at=1000.0)},
        path=path,
    )

    cached = read_cache(path)
    assert cached == {"sase-github": CachedLatest(version="0.5.0", fetched_at=1000.0)}
    assert not list(tmp_path.glob("*.tmp"))

    path.write_text(json.dumps({"schema_version": 999, "entries": {}}))
    assert read_cache(path) == {}


def test_latest_cache_freshness() -> None:
    cached = CachedLatest(version="0.5.0", fetched_at=1000.0)

    assert is_fresh(cached, 1000.0 + 60)
    assert not is_fresh(cached, 1000.0 + 99, ttl_seconds=30)


def test_installed_source_from_direct_url() -> None:
    editable = json.dumps({"dir_info": {"editable": True}})
    git = json.dumps({"vcs_info": {"vcs": "git"}})

    assert (
        installed_source(
            "sase-dev", distribution_fn=lambda _name: _Distribution(editable)
        )
        == "editable"
    )
    assert (
        installed_source("sase-git", distribution_fn=lambda _name: _Distribution(git))
        == "git"
    )
    assert (
        installed_source(
            "sase-index", distribution_fn=lambda _name: _Distribution(None)
        )
        == "index"
    )


def test_is_newer_uses_pep_440_and_degrades_on_invalid_versions() -> None:
    assert is_newer("1.10.0", "1.9.0") is True
    assert is_newer("1.0.0", "1.0.0") is False
    assert is_newer("1.0.0rc1", "1.0.0") is False
    assert is_newer("not a version", "1.0.0") is False


def test_enrich_cache_hit_avoids_fetch() -> None:
    catalog = _catalog(_entry("github", installed=True, version="0.4.0"))

    def _fetch(_dist_name: str) -> str | None:
        raise AssertionError("fresh cache hit must not fetch")

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=_fetch,
        read_cache_fn=lambda: {
            "sase-github": CachedLatest(version="0.5.0", fetched_at=900.0)
        },
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
    )

    entry = enriched.entries[0]
    assert entry.latest.version == "0.5.0"
    assert entry.update_available is True


def test_enrich_offline_miss_makes_zero_fetches() -> None:
    calls: list[str] = []
    catalog = _catalog(_entry("github", installed=True, version="0.4.0"))

    enriched = enrich_with_latest(
        catalog,
        offline=True,
        fetch_fn=lambda dist: calls.append(dist) or "0.5.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
    )

    assert calls == []
    assert enriched.entries[0].latest.error == "offline"
    assert enriched.entries[0].latest.source == "unknown"


def test_enrich_refresh_bypasses_cache_and_writes() -> None:
    writes: list[dict[str, CachedLatest]] = []
    catalog = _catalog(_entry("github", installed=True, version="0.4.0"))

    enriched = enrich_with_latest(
        catalog,
        refresh=True,
        fetch_fn=lambda _dist: "0.6.0",
        read_cache_fn=lambda: {
            "sase-github": CachedLatest(version="0.5.0", fetched_at=999.0)
        },
        write_cache_fn=lambda entries: writes.append(entries),
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        max_workers=1,
    )

    assert enriched.entries[0].latest.version == "0.6.0"
    assert writes[0]["sase-github"] == CachedLatest(version="0.6.0", fetched_at=1000.0)


def test_enrich_one_fetch_failure_does_not_sink_batch() -> None:
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram", installed=True, version="0.1.0"),
    )

    def _fetch(dist: str) -> str | None:
        if dist == "sase-github":
            raise OSError("boom")
        return "0.2.0"

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=_fetch,
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        max_workers=1,
    )
    by_name = {entry.name: entry for entry in enriched.entries}

    assert by_name["github"].latest.version is None
    assert by_name["github"].latest.error == "unavailable"
    assert by_name["telegram"].latest.version == "0.2.0"


def test_enrich_editable_install_is_not_compared_or_fetched() -> None:
    catalog = _catalog(_entry("devkit", installed=True, version="0.1.0"))

    def _fetch(_dist_name: str) -> str | None:
        raise AssertionError("editable installs must not fetch")

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=_fetch,
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "editable",
    )

    entry = enriched.entries[0]
    assert entry.latest.source == "editable"
    assert entry.update_available is False
