from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent_clis.latest import (
    CachedLatest,
    LatestQuery,
    _fetch_npm_latest_version,
    _fetch_url_latest_version,
    get_latest_versions,
    read_cache,
    write_cache,
)

_CHANNEL_URL = "https://api.example.test/muse-code/channels/muse-stable"


class _Response:
    def __init__(self, payload: bytes = b'{"version":"2.3.4"}') -> None:
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_fetch_npm_latest_version_encodes_scoped_package() -> None:
    seen: list[str] = []

    def open_url(request: object, *, timeout: float) -> _Response:
        seen.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 5.0
        return _Response()

    version = _fetch_npm_latest_version("@scope/tool", urlopen_fn=open_url)

    assert version == "2.3.4"
    assert seen == ["https://registry.npmjs.org/%40scope%2Ftool/latest"]


def test_latest_cache_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    entries = {"tool": CachedLatest("1.2.3", 100.0)}

    write_cache(entries, path=path)

    assert read_cache(path) == entries


def test_fetch_url_latest_version_reads_the_declared_field() -> None:
    seen: list[str] = []

    def open_url(request: object, *, timeout: float) -> _Response:
        seen.append(request.full_url)  # type: ignore[attr-defined]
        assert timeout == 5.0
        return _Response(b'{"channel":"muse-stable","version":"0.1.0-R708.1"}')

    version = _fetch_url_latest_version(_CHANNEL_URL, urlopen_fn=open_url)

    assert version == "0.1.0-R708.1"
    assert seen == [_CHANNEL_URL]


@pytest.mark.parametrize(
    "payload",
    [b"not json", b'{"version":123}', b'{"other":"1.0"}', b'["1.0"]'],
)
def test_fetch_url_latest_version_degrades_on_unusable_payloads(
    payload: bytes,
) -> None:
    version = _fetch_url_latest_version(
        _CHANNEL_URL, urlopen_fn=lambda _request, timeout: _Response(payload)
    )

    assert version is None


def test_fetch_url_latest_version_rejects_non_https_urls() -> None:
    def open_url(_request: object, *, timeout: float) -> _Response:
        raise AssertionError("must not open a non-HTTPS URL")

    assert (
        _fetch_url_latest_version("http://example.test/v", urlopen_fn=open_url) is None
    )


def test_npm_and_url_queries_share_one_cache_without_colliding() -> None:
    writes: list[dict[str, CachedLatest]] = []
    fetched: list[LatestQuery] = []

    def fetch(query: LatestQuery) -> str:
        fetched.append(query)
        return "1.0.0" if query.kind == "npm" else "0.1.0-R708.1"

    latest = get_latest_versions(
        ["tool", LatestQuery.for_url(_CHANNEL_URL)],
        read_cache_fn=dict,
        write_cache_fn=writes.append,
        fetch_fn=fetch,
        clock=lambda: 100.0,
    )

    assert latest["npm:tool"].version == "1.0.0"
    assert latest[f"url:{_CHANNEL_URL}"].version == "0.1.0-R708.1"
    assert [query.target for query in fetched] == ["tool", _CHANNEL_URL]
    assert set(writes[-1]) == {"npm:tool", f"url:{_CHANNEL_URL}"}


def test_url_query_field_is_forwarded_to_the_oracle() -> None:
    fetched: list[LatestQuery] = []

    get_latest_versions(
        [LatestQuery.for_url(_CHANNEL_URL, field="min_version")],
        read_cache_fn=dict,
        write_cache_fn=lambda _entries: None,
        fetch_fn=lambda query: (fetched.append(query), "9.9.9")[1],
        clock=lambda: 100.0,
    )

    assert fetched[0].field == "min_version"


def test_fresh_cache_avoids_fetch_and_refresh_replaces_it() -> None:
    writes: list[dict[str, CachedLatest]] = []
    fetched: list[str] = []

    def fetch(query: LatestQuery) -> str:
        fetched.append(query.target)
        return "2.0.0"

    cached = {"npm:tool": CachedLatest("1.0.0", 90.0)}
    fresh = get_latest_versions(
        ["tool"],
        read_cache_fn=lambda: cached,
        write_cache_fn=writes.append,
        fetch_fn=fetch,
        clock=lambda: 100.0,
        ttl_seconds=20.0,
    )
    refreshed = get_latest_versions(
        ["tool"],
        refresh=True,
        read_cache_fn=lambda: cached,
        write_cache_fn=writes.append,
        fetch_fn=fetch,
        clock=lambda: 100.0,
        ttl_seconds=20.0,
    )

    assert fresh["npm:tool"].version == "1.0.0"
    assert fresh["npm:tool"].cached is True
    assert refreshed["npm:tool"].version == "2.0.0"
    assert fetched == ["tool"]
    assert writes[-1]["npm:tool"] == CachedLatest("2.0.0", 100.0)


def test_offline_uses_stale_cache_and_never_fetches() -> None:
    latest = get_latest_versions(
        [LatestQuery.for_url(_CHANNEL_URL), "missing"],
        offline=True,
        read_cache_fn=lambda: {f"url:{_CHANNEL_URL}": CachedLatest("1.0.0", 0.0)},
        write_cache_fn=lambda _entries: None,
        fetch_fn=lambda _query: (_ for _ in ()).throw(AssertionError("must not fetch")),
        clock=lambda: 1000.0,
        ttl_seconds=10.0,
    )

    assert latest[f"url:{_CHANNEL_URL}"].version == "1.0.0"
    assert latest[f"url:{_CHANNEL_URL}"].error == "offline_stale_cache"
    assert latest["npm:missing"].error == "offline"


def test_url_fetch_failure_degrades_to_registry_unavailable() -> None:
    latest = get_latest_versions(
        [LatestQuery.for_url(_CHANNEL_URL)],
        read_cache_fn=dict,
        write_cache_fn=lambda _entries: None,
        fetch_fn=lambda _query: None,
        clock=lambda: 100.0,
    )

    assert latest[f"url:{_CHANNEL_URL}"].version is None
    assert latest[f"url:{_CHANNEL_URL}"].error == "registry_unavailable"
