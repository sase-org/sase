"""Offline fleet response fixtures for TUI tests and benches."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.dispatch.federation import (
    FederationConfig,
    FederationHostConfig,
    FederationWorkerSettings,
)
from sase.dispatch.follow_store import FollowStoreSnapshot


def fleet_installation_id(hex_char: str = "a") -> str:
    """Return a stable fleet installation ID for tests."""
    return f"sase_inst_v1_{hex_char * 64}"


def fleet_logical_locator(
    *,
    installation_id: str | None = None,
    project_id: str = "sase-main",
    agent_id: str = "agent-1",
    family_id: str | None = "family-1",
) -> dict[str, Any]:
    """Build the logical-locator shape consumed by fleet projections."""
    origin_id = installation_id or fleet_installation_id()
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": {
                "schema_version": 1,
                "installation_id": origin_id,
            },
            "project_id": project_id,
        },
        "agent_id": agent_id,
        "family_id": family_id,
    }


def fleet_logical_key(locator: Mapping[str, Any]) -> str:
    """Return the fixture logical key corresponding to a locator."""
    project = locator.get("project")
    origin: object = None
    if isinstance(project, Mapping):
        origin = project.get("origin")
    installation_id = (
        origin.get("installation_id")
        if isinstance(origin, Mapping)
        else locator.get("installation_id")
    )
    agent_id = locator.get("agent_id")
    return f"{installation_id}:{agent_id}"


def fleet_summary(
    *,
    installation_id: str | None = None,
    agent_id: str = "agent-1",
    run_id: str = "run-1",
    logical_key: str | None = None,
    exact_key: str | None = None,
    status: str = "running",
    revision: int = 1,
    patch_name: str = "remote-dispatch",
    agent_name: str | None = None,
    model: str = "gpt-5",
    bounded_intent: str = "exercise fleet projection",
    needs_attention: bool = False,
) -> dict[str, Any]:
    """Build one resolved remote row summary without Rust bindings."""
    origin_id = installation_id or fleet_installation_id()
    logical = fleet_logical_locator(
        installation_id=origin_id,
        agent_id=agent_id,
    )
    logical_key = logical_key or f"{origin_id}:{agent_id}"
    exact_key = exact_key or f"{logical_key}:{run_id}"
    row_revision = {
        "schema_version": 1,
        "logical_key": logical_key,
        "revision": revision,
    }
    return {
        "schema_version": 1,
        "logical_locator": logical,
        "exact_locator": {
            "schema_version": 1,
            "logical": logical,
            "shell_id": f"shell-{agent_id}",
            "run_id": run_id,
            "attempt_id": "attempt-1",
        },
        "logical_key": logical_key,
        "exact_key": exact_key,
        "status": status,
        "needs_attention": needs_attention,
        "revision": revision,
        "row_revision": row_revision,
        "liveness": {
            "schema_version": 1,
            "status": "alive" if status in {"running", "asking"} else "stopped",
            "connection_health": "online",
        },
        "content": {
            "agent_name": agent_name or agent_id,
            "patch_name": patch_name,
            "model": model,
            "bounded_intent": bounded_intent,
        },
        "capabilities": {
            "schema_version": 1,
            "resource": ["content.read", "stop"],
            "host": [],
            "protocol": ["fleet.v1"],
        },
    }


def fleet_host_response(
    *,
    alias: str = "apollo",
    installation_id: str | None = None,
    summaries: Iterable[Mapping[str, Any]] | None = None,
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float | None = 1_800_000_000.0,
    counts: Mapping[str, Any] | None = None,
    diagnostics: Iterable[Mapping[str, Any]] = (),
    partial: bool = False,
) -> dict[str, Any]:
    """Build a federation read response containing one host."""
    origin_id = installation_id or fleet_installation_id()
    summary_list = [dict(summary) for summary in summaries or ()]
    host_counts = dict(counts) if counts is not None else _counts_for(summary_list)
    response: dict[str, Any] = {
        "schema_version": 1,
        "configured_hosts": 1,
        "counts": {"hosts": 1, **host_counts},
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "origin": {
                    "schema_version": 1,
                    "alias": alias,
                    "installation_id": origin_id,
                },
                "origin_installation_id": origin_id,
                "freshness": freshness,
                "connection_health": connection_health,
                "observed_at_unix": observed_at_unix,
                "counts": host_counts,
                "summaries": summary_list,
            }
        ],
    }
    diagnostic_list = [dict(diagnostic) for diagnostic in diagnostics]
    if diagnostic_list:
        response["diagnostics"] = diagnostic_list
    if partial:
        response["partial"] = True
    return response


def _counts_for(summaries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    running_statuses = {"active", "alive", "asking", "running", "started", "starting"}
    summary_list = list(summaries)
    return {
        "total": len(summary_list),
        "running": sum(
            1
            for summary in summary_list
            if str(summary.get("status") or "").casefold() in running_statuses
        ),
    }


def fleet_attention_response(
    entries: Iterable[Mapping[str, Any]],
    *,
    alias: str = "apollo",
) -> dict[str, Any]:
    """Build a federation attention response for logical-key lookups."""
    return {
        "schema_version": 1,
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "payload": {"entries": [dict(entry) for entry in entries]},
            }
        ],
    }


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


@dataclass
class OfflineFleetFacade:
    """Fake federation facade with response counters and no external effects."""

    summary_response: Mapping[str, Any] | None = None
    catalog_response: Mapping[str, Any] | None = None
    followed_response: Mapping[str, Any] | None = None
    attention_response: Mapping[str, Any] | None = None
    calls: list[str] = field(default_factory=list)

    async def summary(
        self,
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        del cache_only, timeout_seconds
        self.calls.append("summary")
        return dict(self.summary_response or fleet_host_response())

    async def catalog(
        self,
        query: Mapping[str, Any],
        *,
        cache_only: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        del query, cache_only, timeout_seconds
        self.calls.append("catalog")
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
        del request, cache_only, timeout_seconds
        self.calls.append("followed_batch")
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
        del request, cache_only, timeout_seconds
        self.calls.append("attention")
        return dict(self.attention_response or fleet_attention_response(()))
