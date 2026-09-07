"""Async read facade backed by the local worker when hosts are configured."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.dispatch.models import MachineDiagnostic

from ._constants import FEDERATION_IPC_SCHEMA_VERSION, FEDERATION_WORKER_COMMAND
from ._errors import FederationWorkerUnavailable
from ._hosts import FederationConfig, diagnostic_wire, load_federation_config
from ._supervisor import FederationWorkerSupervisor


def build_federation_facade(
    config: FederationConfig | None = None,
    *,
    supervisor: FederationWorkerSupervisor | None = None,
) -> FederationFacade:
    """Return the remote-fleet facade for the current configuration."""

    config = config or load_federation_config()
    return FederationFacade(config, supervisor=supervisor)


@dataclass
class FederationFacade:
    """Async read facade backed by the local worker when hosts are configured."""

    config: FederationConfig
    supervisor: FederationWorkerSupervisor | None = None

    def __post_init__(self) -> None:
        if self.supervisor is None and self.config.enabled:
            self.supervisor = FederationWorkerSupervisor(self.config)

    async def health(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.health_sync, timeout_seconds=timeout_seconds
        )

    async def summary(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.summary_sync,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def catalog(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.catalog_sync,
            query,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def followed_batch(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.followed_batch_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def detail(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.detail_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def content_range(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.content_range_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def project_eligibility(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.project_eligibility_sync,
            request,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
        )

    async def launch(
        self,
        target: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.launch_sync,
            target,
            request,
            timeout_seconds=timeout_seconds,
        )

    def health_sync(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            payload: dict[str, Any] = {
                "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
                "status": "disabled",
                "service": FEDERATION_WORKER_COMMAND,
                "configured_hosts": 0,
                "capabilities": [],
            }
            if self.config.diagnostics:
                payload["diagnostics"] = self.config.diagnostics_wire()
            return payload
        return self._request({"op": "health"}, timeout_seconds=timeout_seconds)

    def summary_sync(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "summary",
            {"op": "summary", "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def catalog_sync(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "catalog",
            {"op": "catalog", "query": dict(query), "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def followed_batch_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "followed_batch",
            {
                "op": "followed_batch",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def detail_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "detail",
            {"op": "detail", "request": dict(request), "cache_only": cache_only},
            timeout_seconds=timeout_seconds,
        )

    def content_range_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "content_range",
            {
                "op": "content_range",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def project_eligibility_sync(
        self,
        request: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return self._read(
            "project_eligibility",
            {
                "op": "project_eligibility",
                "request": dict(request),
                "cache_only": cache_only,
            },
            timeout_seconds=timeout_seconds,
        )

    def launch_sync(
        self,
        target: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise FederationWorkerUnavailable(
                "no configured dispatch machines are available"
            )
        return self._request(
            {"op": "launch", "target": target, "request": dict(request)},
            timeout_seconds=timeout_seconds,
        )

    async def mutate(
        self,
        target: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.mutate_sync,
            target,
            request,
            timeout_seconds=timeout_seconds,
        )

    def mutate_sync(
        self,
        target: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            raise FederationWorkerUnavailable(
                "no configured dispatch machines are available"
            )
        return self._request(
            {"op": "mutate", "target": target, "request": dict(request)},
            timeout_seconds=timeout_seconds,
        )

    def shutdown_sync(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"schema_version": FEDERATION_IPC_SCHEMA_VERSION, "shutdown": False}
        return self._request(
            {"op": "shutdown"},
            timeout_seconds=timeout_seconds,
            retry=False,
        )

    def _read(
        self,
        operation: str,
        request: Mapping[str, Any],
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return _disabled_read(operation, diagnostics=self.config.diagnostics)
        return self._request(request, timeout_seconds=timeout_seconds)

    def _request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float | None,
        retry: bool = True,
    ) -> dict[str, Any]:
        if self.supervisor is None:
            raise FederationWorkerUnavailable(
                "federation worker supervisor is disabled"
            )
        return self.supervisor.request(
            operation, timeout_seconds=timeout_seconds, retry=retry
        )


def _disabled_read(
    operation: str,
    *,
    diagnostics: Sequence[MachineDiagnostic] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
        "operation": operation,
        "disabled": True,
        "hosts": [],
    }
    if diagnostics:
        payload["diagnostics"] = [diagnostic_wire(item) for item in diagnostics]
    return payload
