"""Tests for latest-version lookup, caching, and catalog enrichment."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any, Literal

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.dev_update.models import DevLatest
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import (
    LatestInfo,
    enrich_entry_latest,
    enrich_with_latest,
    installed_source,
    is_newer,
    latest_cache_key,
)
from sase.plugins.latest_cache import (
    LATEST_CACHE_MAX_AGE_SECONDS,
    CachedLatest,
    is_fresh,
    prune_latest_cache,
    read_cache,
    write_cache,
)
from sase.plugins.pypi_source import fetch_latest_version
from sase.version._models import VersionPackageRecord


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


def _record(
    name: str,
    *,
    display_version: str = "0.1.0+1.gabc123def",
    install_type: Literal["editable", "wheel", "unknown"] = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role="plugin",
        display_version=display_version,
        distribution_version="0.1.0",
        source_version="0.1.0",
        import_module=name.replace("-", "_"),
        import_path=None,
        code_directory="/src/pkg",
        source_root="/src/pkg",
        distribution_location=None,
        install_type=install_type,
        git=None,
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
        now=1000.0,
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


def test_is_newer_degrades_when_packaging_is_absent(
    monkeypatch: Any,
) -> None:
    real_import = __import__

    def _no_packaging(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "packaging.version" or name.startswith("packaging"):
            raise ModuleNotFoundError("No module named 'packaging'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_packaging)

    assert is_newer("1.10.0", "1.9.0") is False


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
        version_records_fn=lambda: (),
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
        version_records_fn=lambda: (),
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
        version_records_fn=lambda: (),
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
        version_records_fn=lambda: (),
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
        version_records_fn=lambda: (),
    )

    entry = enriched.entries[0]
    assert entry.latest.source == "editable"
    assert entry.update_available is False


def test_enrich_editable_install_uses_dev_latest_detection() -> None:
    record = _record("sase-devkit")
    catalog = _catalog(_entry("devkit", installed=True, version="0.1.0"))
    seen: list[tuple[str, bool]] = []

    def _detect(package: VersionPackageRecord, *, offline: bool) -> DevLatest:
        seen.append((package.name, offline))
        return DevLatest(
            record=package,
            state="update_available",
            reason="behind upstream by 2 commit(s)",
            current_version=package.display_version,
            latest_version="0.1.0+3.gdef456abc",
            update_available=True,
            git_root="/src/pkg",
            upstream="origin/main",
            ahead=0,
            behind=2,
        )

    enriched = enrich_with_latest(
        catalog,
        offline=True,
        fetch_fn=lambda _dist: (_ for _ in ()).throw(AssertionError("no fetch")),
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (record,),
        detect_dev_latest_fn=_detect,
    )

    entry = enriched.entries[0]
    assert seen == [("sase-devkit", True)]
    assert entry.latest.source == "editable"
    assert entry.latest.current_version == "0.1.0+1.gabc123def"
    assert entry.latest.version == "0.1.0+3.gdef456abc"
    assert entry.latest.state == "update_available"
    assert entry.latest.reason == "behind upstream by 2 commit(s)"
    assert entry.update_available is True


def test_latest_cache_write_prunes_entries_older_than_max_age(tmp_path: Path) -> None:
    path = tmp_path / "latest_cache.json"
    now = 10_000.0
    write_cache(
        {
            "sase-fresh": CachedLatest(version="1.0.0", fetched_at=now - 60.0),
            "sase-stale": CachedLatest(
                version="0.1.0",
                fetched_at=now - LATEST_CACHE_MAX_AGE_SECONDS - 1.0,
            ),
        },
        path=path,
        now=now,
    )

    cached = read_cache(path)
    assert cached == {
        "sase-fresh": CachedLatest(version="1.0.0", fetched_at=now - 60.0)
    }
    pruned = prune_latest_cache(
        {
            "sase-fresh": CachedLatest(version="1.0.0", fetched_at=now - 60.0),
            "sase-stale": CachedLatest(
                version="0.1.0",
                fetched_at=now - LATEST_CACHE_MAX_AGE_SECONDS - 1.0,
            ),
        },
        now,
    )
    assert set(pruned) == {"sase-fresh"}


def test_enrich_installed_scope_skips_uninstalled_fetches() -> None:
    calls: list[str] = []
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram"),
    )

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=lambda dist: calls.append(dist) or "1.0.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        scope="installed",
    )
    by_name = {entry.name: entry for entry in enriched.entries}

    assert calls == ["sase-github"]
    assert by_name["github"].latest.version == "1.0.0"
    assert by_name["telegram"].latest == LatestInfo.unknown()
    assert latest_cache_key(by_name["github"]) == "sase-github"


def test_enrich_default_scope_is_installed_only() -> None:
    calls: list[str] = []
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram"),
    )

    enrich_with_latest(
        catalog,
        fetch_fn=lambda dist: calls.append(dist) or "1.0.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
    )

    assert calls == ["sase-github"]


def test_enrich_all_scope_fetches_uninstalled() -> None:
    calls: list[str] = []
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram"),
    )

    enrich_with_latest(
        catalog,
        fetch_fn=lambda dist: calls.append(dist) or "1.0.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        scope="all",
    )

    assert calls == ["sase-github", "sase-telegram"]


def test_enrich_refresh_keeps_out_of_scope_cache_rows() -> None:
    writes: list[dict[str, CachedLatest]] = []
    catalog = _catalog(_entry("github", installed=True, version="0.4.0"))

    enrich_with_latest(
        catalog,
        refresh=True,
        fetch_fn=lambda _dist: "0.6.0",
        read_cache_fn=lambda: {
            "sase-github": CachedLatest(version="0.5.0", fetched_at=999.0),
            "sase-other": CachedLatest(version="9.9.9", fetched_at=999.0),
        },
        write_cache_fn=lambda entries: writes.append(entries),
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        scope="installed",
    )

    assert writes[0]["sase-github"] == CachedLatest(version="0.6.0", fetched_at=1000.0)
    assert writes[0]["sase-other"] == CachedLatest(version="9.9.9", fetched_at=999.0)


def test_enrich_deadline_marks_remaining_misses_unavailable() -> None:
    ticks = iter([0.0, 0.0, 10.0, 10.0])
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram", installed=True, version="0.1.0"),
    )

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=lambda dist: "1.0.0" if dist == "sase-github" else "2.0.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        deadline_seconds=1.0,
        monotonic=lambda: next(ticks),
    )
    by_name = {entry.name: entry for entry in enriched.entries}

    assert by_name["github"].latest.version == "1.0.0"
    assert by_name["telegram"].latest.version is None
    assert by_name["telegram"].latest.error == "unavailable"


def test_enrich_include_keys_fetches_uninstalled_when_scoped() -> None:
    calls: list[str] = []
    catalog = _catalog(
        _entry("github", installed=True, version="0.4.0"),
        _entry("telegram"),
    )

    enriched = enrich_with_latest(
        catalog,
        fetch_fn=lambda dist: calls.append(dist) or "3.0.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
        max_workers=1,
        scope="installed",
        include_keys=("sase-telegram",),
    )
    by_name = {entry.name: entry for entry in enriched.entries}

    assert set(calls) == {"sase-github", "sase-telegram"}
    assert by_name["telegram"].latest.version == "3.0.0"


def test_enrich_entry_latest_fetches_one_uninstalled_row() -> None:
    calls: list[str] = []
    entry = enrich_entry_latest(
        _entry("telegram"),
        fetch_fn=lambda dist: calls.append(dist) or "4.1.0",
        read_cache_fn=lambda: {},
        write_cache_fn=lambda _entries: None,
        clock=lambda: 1000.0,
        installed_source_fn=lambda _dist: "index",
        version_records_fn=lambda: (),
    )

    assert calls == ["sase-telegram"]
    assert entry.latest.version == "4.1.0"
    assert entry.latest.checked is True
