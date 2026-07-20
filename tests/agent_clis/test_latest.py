from __future__ import annotations

from pathlib import Path

from sase.agent_clis.latest import (
    CachedLatest,
    _fetch_npm_latest_version,
    get_latest_versions,
    read_cache,
    write_cache,
)


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"version":"2.3.4"}'


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


def test_fresh_cache_avoids_fetch_and_refresh_replaces_it() -> None:
    writes: list[dict[str, CachedLatest]] = []
    fetched: list[str] = []

    def fetch(package: str) -> str:
        fetched.append(package)
        return "2.0.0"

    cached = {"tool": CachedLatest("1.0.0", 90.0)}
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

    assert fresh["tool"].version == "1.0.0"
    assert fresh["tool"].cached is True
    assert refreshed["tool"].version == "2.0.0"
    assert fetched == ["tool"]
    assert writes[-1]["tool"] == CachedLatest("2.0.0", 100.0)


def test_offline_uses_stale_cache_and_never_fetches() -> None:
    latest = get_latest_versions(
        ["cached", "missing"],
        offline=True,
        read_cache_fn=lambda: {"cached": CachedLatest("1.0.0", 0.0)},
        write_cache_fn=lambda _entries: None,
        fetch_fn=lambda _package: (_ for _ in ()).throw(
            AssertionError("must not fetch")
        ),
        clock=lambda: 1000.0,
        ttl_seconds=10.0,
    )

    assert latest["cached"].version == "1.0.0"
    assert latest["cached"].error == "offline_stale_cache"
    assert latest["missing"].error == "offline"
