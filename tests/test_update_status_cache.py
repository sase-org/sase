"""Tests for cached update-status orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent_clis.models import AgentCliStatus
from sase.plugins.latest_cache import CachedLatest
from sase.updates import (
    OutdatedComponent,
    ProviderUpdateCandidate,
    UpdateSourceStatus,
    UpdateStatus,
    get_cached_update_status,
    write_update_status_snapshot,
)
from tests._update_status_helpers import agent_cli_status


def test_get_cached_update_status_uses_fresh_snapshot_without_compute(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("fresh cache should not compute")

    result = get_cached_update_status(
        path=path,
        now=110.0,
        ttl_seconds=20,
        compute_fn=_compute,
        version_fn=lambda _dist_name: "0.5.0",
    )

    assert result == status


def test_get_cached_update_status_revalidate_only_uses_stale_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(checked_at=100.0, components=())
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("revalidate-only mode must never compute")

    result = get_cached_update_status(
        path=path,
        now=10_000.0,
        ttl_seconds=20.0,
        revalidate_only=True,
        compute_fn=_compute,
    )

    assert result == status


def test_ordinary_tick_revalidates_named_candidates_without_full_inventory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    candidate = ProviderUpdateCandidate("claude", "Claude Code", "1.0.0", "2.0.0")
    status = UpdateStatus(
        checked_at=100.0,
        components=(),
        provider_candidates=(candidate,),
    )
    write_update_status_snapshot(status, path=path)
    named_calls: list[tuple[str, ...]] = []

    def local_status(names: tuple[str, ...]) -> tuple[AgentCliStatus, ...]:
        named_calls.append(names)
        return (agent_cli_status("claude", installed_version="1.1.0"),)

    result = get_cached_update_status(
        path=path,
        now=10_000.0,
        revalidate_only=True,
        compute_fn=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("ordinary ticks must not run full/network discovery")
        ),
        provider_status_fn=local_status,
    )

    assert result is not None
    assert result.provider_candidates == (
        ProviderUpdateCandidate(
            "claude",
            "Claude Code",
            "1.1.0",
            "2.0.0",
        ),
    )
    assert named_calls == [("claude",)]


def test_get_cached_update_status_revalidate_only_does_not_compute_on_miss(
    tmp_path: Path,
) -> None:
    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("revalidate-only mode must never compute")

    result = get_cached_update_status(
        path=tmp_path / "missing.json",
        revalidate_only=True,
        compute_fn=_compute,
    )

    assert result is None


def test_get_cached_update_status_falls_back_to_snapshot_on_compute_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(checked_at=100.0, components=())
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise RuntimeError("offline")

    result = get_cached_update_status(
        path=path,
        now=200.0,
        ttl_seconds=20,
        compute_fn=_compute,
    )

    assert result == status


def test_get_cached_update_status_full_compute_does_not_redetect_providers(
    tmp_path: Path,
) -> None:
    status = UpdateStatus(
        checked_at=200.0,
        components=(),
        provider_candidates=(
            ProviderUpdateCandidate("claude", "Claude", "1.0.0", "2.0.0"),
        ),
        core_source=UpdateSourceStatus.success(200.0),
        plugin_source=UpdateSourceStatus.success(200.0),
        agent_cli_source=UpdateSourceStatus.success(200.0),
    )

    result = get_cached_update_status(
        path=tmp_path / "status.json",
        now=200.0,
        compute_fn=lambda **_kwargs: status,
        provider_status_fn=lambda _names: (_ for _ in ()).throw(
            AssertionError("a full inventory is already locally validated")
        ),
    )

    assert result == status


def test_cached_core_fetch_uses_fresh_latest_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_read_latest_cache",
        lambda: {"sase": CachedLatest(version="1.1.0", fetched_at=100.0)},
    )

    def _no_fetch(_dist_name: str) -> str | None:
        raise AssertionError("a fresh latest-version cache must not hit PyPI")

    monkeypatch.setattr(status_module, "_fetch_latest_version", _no_fetch)

    fetch = status_module._make_cached_core_fetch_fn(now=120.0)

    assert fetch("sase") == "1.1.0"


def test_cached_core_fetch_writes_through_on_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(status_module, "_read_latest_cache", dict)
    monkeypatch.setattr(status_module, "_fetch_latest_version", lambda _d: "2.0.0")
    written: dict[str, CachedLatest] = {}
    monkeypatch.setattr(
        status_module, "_write_latest_cache", lambda cache: written.update(cache)
    )

    fetch = status_module._make_cached_core_fetch_fn(now=500.0)

    assert fetch("sase-core-rs") == "2.0.0"
    assert written == {"sase-core-rs": CachedLatest(version="2.0.0", fetched_at=500.0)}
