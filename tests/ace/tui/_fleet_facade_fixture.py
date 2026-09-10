"""Federation facade/config fixtures for offline Fleet TUI tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.dispatch.federation import (
    FederationConfig,
    FederationHostConfig,
    FederationWorkerSettings,
)
from sase.dispatch.follow_store import FollowStoreSnapshot
from tests.ace.tui._fleet_locator_fixture import (
    fleet_installation_id,
    fleet_logical_key,
)
from tests.ace.tui._fleet_response_fixture import (
    fleet_attention_response,
    fleet_host_response,
)


def fleet_follow_snapshot(
    *locators: Mapping[str, Any],
    path: str = "/tmp/sase-fleet-follows.json",
) -> FollowStoreSnapshot:
    """Build an active follow-store snapshot for the provided locators."""
    records: list[dict[str, Any]] = []
    for locator in locators:
        records.append(
            {
                "schema_version": 1,
                "state": "active",
                "logical_key": fleet_logical_key(locator),
                "logical_locator": dict(locator),
                "created_by": "explicit",
                "created_at_unix": 1_800_000_000.0,
                "updated_at_unix": 1_800_000_000.0,
                "activated_at_unix": 1_800_000_000.0,
            }
        )
    return FollowStoreSnapshot(
        schema_version=1,
        records=tuple(records),
        tombstones=(),
        path=path,
    )


def fleet_config(*, enabled: bool = True) -> FederationConfig:
    """Build a federation config that never starts a real worker."""
    host = (
        FederationHostConfig(
            alias="apollo",
            plan={
                "schema_version": 1,
                "provider_ref": "builtin:https",
                "endpoint": "https://apollo.example.test",
                "credential_ref": "fleet:apollo",
                "pinned_installation_id": fleet_installation_id(),
                "connection_kind": "gateway",
            },
            bearer_token="test-token",
            origin_installation_id=fleet_installation_id(),
        ),
    )
    return FederationConfig(
        worker=FederationWorkerSettings(enabled=enabled),
        hosts=host if enabled else (),
    )


def fleet_config_for_hosts(
    *hosts: tuple[str, str],
    enabled: bool = True,
) -> FederationConfig:
    """Build a multi-host federation config that never starts a real worker."""
    return FederationConfig(
        worker=FederationWorkerSettings(enabled=enabled),
        hosts=()
        if not enabled
        else tuple(
            FederationHostConfig(
                alias=alias,
                plan={
                    "schema_version": 1,
                    "provider_ref": "builtin:https",
                    "endpoint": f"https://{alias}.example.test",
                    "credential_ref": f"fleet:{alias}",
                    "pinned_installation_id": installation_id,
                    "connection_kind": "gateway",
                },
                bearer_token=f"test-token-{alias}",
                origin_installation_id=installation_id,
            )
            for alias, installation_id in hosts
        ),
    )


@dataclass
class OfflineFleetFacade:
    """Fake federation facade with response counters and no external effects."""

    summary_response: Mapping[str, Any] | None = None
    catalog_response: Mapping[str, Any] | None = None
    followed_response: Mapping[str, Any] | None = None
    attention_response: Mapping[str, Any] | None = None
    calls: list[str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def summary(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("summary")
        self.requests.append(
            {
                "operation": "summary",
                "request": None,
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return dict(self.summary_response or fleet_host_response())

    async def catalog(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("catalog")
        self.requests.append(
            {
                "operation": "catalog",
                "request": dict(query),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return dict(
            self.catalog_response or self.summary_response or fleet_host_response()
        )

    async def catalog_hosts(
        self,
        queries: Iterable[Mapping[str, Any]],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("catalog_hosts")
        self.requests.append(
            {
                "operation": "catalog_hosts",
                "request": [dict(query) for query in queries],
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return dict(
            self.catalog_response or self.summary_response or fleet_host_response()
        )

    async def followed_batch(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("followed_batch")
        self.requests.append(
            {
                "operation": "followed_batch",
                "request": dict(request),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return dict(
            self.followed_response or self.summary_response or fleet_host_response()
        )

    async def attention(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("attention")
        self.requests.append(
            {
                "operation": "attention",
                "request": dict(request),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return dict(self.attention_response or fleet_attention_response(()))


@dataclass
class ScriptedFleetFacade(OfflineFleetFacade):
    """Offline facade with per-operation response scripts and async delays."""

    scripts: Mapping[str, Iterable[Mapping[str, Any] | Exception]] = field(
        default_factory=dict
    )
    delays: Mapping[str, float] = field(default_factory=dict)
    _scripts: dict[str, list[Mapping[str, Any] | Exception]] = field(
        default_factory=dict,
        init=False,
    )
    # Per-operation (perf_counter_start, perf_counter_end) spans covering each
    # scripted call's delay, in the same clock as JKPerfTimer's samples, so a
    # caller can prove a scripted response resolved during a measured window
    # rather than trusting incidental timing.
    call_windows: dict[str, list[tuple[float, float]]] = field(
        default_factory=dict,
        init=False,
    )

    def __post_init__(self) -> None:
        self._scripts = {
            operation: list(steps) for operation, steps in self.scripts.items()
        }

    async def _scripted(
        self,
        operation: str,
        default: Mapping[str, Any],
    ) -> dict[str, Any]:
        start = time.perf_counter()
        delay = float(self.delays.get(operation, 0.0) or 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
        steps = self._scripts.get(operation)
        step = steps.pop(0) if steps else default
        self.call_windows.setdefault(operation, []).append((start, time.perf_counter()))
        if isinstance(step, Exception):
            raise step
        return dict(step)

    async def summary(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("summary")
        self.requests.append(
            {
                "operation": "summary",
                "request": None,
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return await self._scripted(
            "summary", self.summary_response or fleet_host_response()
        )

    async def catalog(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("catalog")
        self.requests.append(
            {
                "operation": "catalog",
                "request": dict(query),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        default = (
            self.catalog_response or self.summary_response or fleet_host_response()
        )
        return await self._scripted("catalog", default)

    async def catalog_hosts(
        self,
        queries: Iterable[Mapping[str, Any]],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("catalog_hosts")
        self.requests.append(
            {
                "operation": "catalog_hosts",
                "request": [dict(query) for query in queries],
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        default = (
            self.catalog_response or self.summary_response or fleet_host_response()
        )
        return await self._scripted("catalog_hosts", default)

    async def followed_batch(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("followed_batch")
        self.requests.append(
            {
                "operation": "followed_batch",
                "request": dict(request),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        default = (
            self.followed_response or self.summary_response or fleet_host_response()
        )
        return await self._scripted("followed_batch", default)

    async def attention(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append("attention")
        self.requests.append(
            {
                "operation": "attention",
                "request": dict(request),
                "cache_only": cache_only,
                "timeout_seconds": timeout_seconds,
            }
        )
        return await self._scripted(
            "attention",
            self.attention_response or fleet_attention_response(()),
        )
