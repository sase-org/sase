"""Offline fleet response fixtures for TUI tests and benches."""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.core.rust import require_rust_binding
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
    """Return the core logical key corresponding to a locator."""
    return str(require_rust_binding("fleet_logical_locator_key")(dict(locator)))


def fleet_exact_locator(
    logical: Mapping[str, Any],
    *,
    agent_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Build the exact instance-locator shape consumed by fleet projections."""
    return {
        "schema_version": 1,
        "logical": copy.deepcopy(dict(logical)),
        "shell_id": f"shell-{agent_id}",
        "run_id": run_id,
        "attempt_id": "attempt-1",
    }


def fleet_exact_key(locator: Mapping[str, Any]) -> str:
    """Return the core exact key corresponding to an instance locator."""
    return str(require_rust_binding("fleet_instance_locator_key")(dict(locator)))


def fleet_summary(
    *,
    installation_id: str | None = None,
    project_id: str = "sase-main",
    project_name: str = "SASE",
    agent_id: str = "agent-1",
    run_id: str = "run-1",
    logical_key: str | None = None,
    exact_key: str | None = None,
    status: str = "running",
    revision: int = 1,
    patch_name: str = "remote-dispatch",
    agent_name: str | None = None,
    model: str = "gpt-5",
    provider: str = "codex",
    bounded_intent: str = "exercise fleet projection",
    needs_attention: bool = False,
    family_id: str | None = "family-1",
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float = 1_800_000_000.0,
    occupied_runner_slot: bool | None = None,
    queue_weight: float | None = None,
    queue_weight_explicit: bool = False,
    queue_weight_invalid: bool = False,
    queue_weight_error: str | None = None,
) -> dict[str, Any]:
    """Build one valid resolved remote row summary."""
    del patch_name  # Remote summaries expose project labels, not Patch labels.
    origin_id = installation_id or fleet_installation_id()
    logical = fleet_logical_locator(
        installation_id=origin_id,
        project_id=project_id,
        agent_id=agent_id,
        family_id=family_id,
    )
    exact = fleet_exact_locator(logical, agent_id=agent_id, run_id=run_id)
    logical_key = logical_key or fleet_logical_key(logical)
    exact_key = exact_key or fleet_exact_key(exact)
    row_revision = {
        "schema_version": 1,
        "logical_key": logical_key,
        "revision": revision,
    }
    bucket = _status_bucket(status)
    lifecycle = _lifecycle_for_status(status)
    liveness = _liveness_for_status(status)
    current_instance = liveness == "alive"
    if occupied_runner_slot is None:
        occupied_runner_slot = current_instance and bucket in {
            "running",
            "starting",
            "waiting",
            "queued",
        }
    summary: dict[str, Any] = {
        "schema_version": 1,
        "logical_locator": logical,
        "exact_locator": exact,
        "logical_key": logical_key,
        "exact_key": exact_key,
        "row_kind": "agent_shell",
        "labels": {
            "schema_version": 1,
            "project_label": project_name,
            "agent_label": agent_name or agent_id,
            "family_label": family_id,
            "owner_label": "bryan",
            "alias": None,
        },
        "project_name": project_name,
        "model": model,
        "provider": provider,
        "status": _display_status(status),
        "status_bucket": bucket,
        "intent": bounded_intent,
        "observed_at_unix": observed_at_unix,
        "row_revision": row_revision,
        "lifecycle": lifecycle,
        "liveness": liveness,
        "connection_health": _connection_health(connection_health),
        "freshness": _freshness(freshness),
        "capabilities": {
            "schema_version": 1,
            "resource": ["content.read", "stop"],
            "host": [],
            "protocol": ["fleet.v1"],
        },
        "content": {
            "schema_version": 1,
            "handle_count": 1,
            "total_byte_len": len(bounded_intent),
            "kinds": ["transcript"],
            "supports_range": True,
            "supports_growth": current_instance,
        },
        "current_instance": current_instance,
        "dismissable": not current_instance,
        "needs_attention": needs_attention,
        "occupied_runner_slot": bool(occupied_runner_slot),
        "container_projected_concrete_agent": False,
    }
    if queue_weight is not None:
        summary["queue_weight"] = queue_weight
    if queue_weight_explicit:
        summary["queue_weight_explicit"] = True
    if queue_weight_invalid:
        summary["queue_weight_invalid"] = True
    if queue_weight_error is not None:
        summary["queue_weight_error"] = queue_weight_error
    return summary


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
    operation: str = "catalog",
) -> dict[str, Any]:
    """Build a federation read response containing one host."""
    origin_id = installation_id or fleet_installation_id()
    summary_list = [
        _summary_with_host_observation(
            dict(summary),
            freshness=freshness,
            connection_health=connection_health,
            observed_at_unix=observed_at_unix,
        )
        for summary in summaries or ()
    ]
    host_counts = (
        dict(counts)
        if counts is not None
        else fleet_counts(summary_list, observed_at_unix=observed_at_unix)
    )
    response: dict[str, Any] = {
        "schema_version": 1,
        "operation": operation,
        "configured_hosts": 1,
        "hosts": [
            {
                "schema_version": 1,
                "alias": alias,
                "provider_ref": f"{alias}-provider",
                "installation_id": origin_id,
                "endpoint": f"https://{alias}.example.test",
                "status": "ok",
                "cached": _freshness(freshness) != "fresh",
                "age_seconds": None,
                "payload": {
                    "schema_version": 1,
                    "cursor": _store_cursor(alias),
                    "counts": host_counts,
                    "count_revision": _max_revision(summary_list),
                    "freshness": _freshness_wire(
                        freshness,
                        observed_at_unix=observed_at_unix,
                        partial=partial,
                    ),
                    "page": {
                        "schema_version": 1,
                        "rows": summary_list,
                        "limit": 100,
                        "total_matching_rows": host_counts["logical_agent_total"],
                        "next_cursor": None,
                        "has_more": False,
                    },
                },
                "error": None,
            }
        ],
    }
    diagnostic_list = [
        _diagnostic(diagnostic, operation=operation) for diagnostic in diagnostics
    ]
    if diagnostic_list:
        response["diagnostics"] = diagnostic_list
    if partial:
        response["partial"] = True
    return response


def fleet_host_payload(
    *,
    alias: str = "apollo",
    installation_id: str | None = None,
    summaries: Iterable[Mapping[str, Any]] | None = None,
    freshness: str = "fresh",
    connection_health: str = "online",
    observed_at_unix: float | None = 1_800_000_000.0,
    counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one host payload for a multi-host federation response."""
    return dict(
        fleet_host_response(
            alias=alias,
            installation_id=installation_id,
            summaries=summaries,
            freshness=freshness,
            connection_health=connection_health,
            observed_at_unix=observed_at_unix,
            counts=counts,
        )["hosts"][0]
    )


def fleet_multi_host_response(
    *hosts: Mapping[str, Any],
    configured_hosts: int | None = None,
    diagnostics: Iterable[Mapping[str, Any]] = (),
    partial: bool = False,
) -> dict[str, Any]:
    """Build a deterministic federation response spanning multiple hosts."""
    host_list = [copy.deepcopy(dict(host)) for host in hosts]
    response: dict[str, Any] = {
        "schema_version": 1,
        "operation": "catalog",
        "configured_hosts": configured_hosts
        if configured_hosts is not None
        else len(host_list),
        "hosts": host_list,
    }
    diagnostic_list = [
        _diagnostic(diagnostic, operation="catalog") for diagnostic in diagnostics
    ]
    if diagnostic_list:
        response["diagnostics"] = diagnostic_list
    if partial:
        response["partial"] = True
    return response


def fleet_fault_diagnostic(
    *,
    alias: str,
    operation: str,
    code: str,
    message: str,
    severity: str = "warning",
) -> dict[str, Any]:
    """Build a host-scoped fault diagnostic for offline Fleet tests."""
    return {
        "schema_version": 1,
        "alias": alias,
        "operation": operation,
        "code": code,
        "severity": severity,
        "message": message,
    }


def _summary_payloads(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    payload = host.get("payload")
    if isinstance(payload, Mapping):
        page = payload.get("page")
        if isinstance(page, Mapping):
            rows = page.get("rows")
            if isinstance(rows, Iterable) and not isinstance(
                rows,
                (str, bytes, bytearray),
            ):
                return tuple(item for item in rows if isinstance(item, Mapping))
    return ()


def fleet_counts(
    summaries: Iterable[Mapping[str, Any]],
    *,
    running: int | None = None,
    observed_at_unix: float | None = None,
) -> dict[str, Any]:
    """Build valid authoritative logical-agent counts for fixture summaries."""
    summary_list = list(summaries)
    total = len(summary_list)
    max_revision = _max_revision(summary_list)
    observed = (
        observed_at_unix
        if observed_at_unix is not None
        else _max_observed_at_unix(summary_list)
    )
    running_count = (
        running
        if running is not None
        else sum(1 for summary in summary_list if _summary_counts_as_running(summary))
    )
    attention_count = sum(
        1 for summary in summary_list if summary.get("needs_attention")
    )
    waiting_count = sum(
        1
        for summary in summary_list
        if str(summary.get("status_bucket") or "").casefold()
        in {"waiting", "queued", "stopped"}
    )
    occupied_count = (
        running_count
        if running is not None
        else sum(
            1 for summary in summary_list if bool(summary.get("occupied_runner_slot"))
        )
    )
    return {
        "schema_version": 1,
        "basis": {
            "schema_version": 1,
            "input_rows": total,
            "selected_rows": total,
            "max_revision": max_revision,
            "observed_at_unix_max": observed,
        },
        "logical_agent_total": total,
        "running": running_count,
        "waiting": waiting_count,
        "attention": attention_count,
        "occupied_runner_slots": occupied_count,
    }


def _store_cursor(alias: str) -> dict[str, Any]:
    safe_alias = "".join(
        character if character.isalnum() or character in "_-" else "_"
        for character in alias
    )
    return {
        "schema_version": 1,
        "store_generation": f"gen-{safe_alias or 'fleet'}",
        "sequence": 1,
    }


def _status_bucket(status: str) -> str:
    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"done", "complete", "completed", "terminal"}:
        return "done"
    if normalized in {"stopped", "cancelled", "canceled"}:
        return "stopped"
    if normalized == "starting":
        return "starting"
    if normalized in {"queued", "pending"}:
        return "queued"
    if normalized in {"waiting", "waiting_input", "needs_input", "blocked"}:
        return "stopped"
    if normalized in {"asking", "question"}:
        return "stopped"
    return "running"


def _lifecycle_for_status(status: str) -> str:
    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"failed", "error"}:
        return "failed"
    if normalized in {"done", "complete", "completed", "terminal"}:
        return "terminal"
    if normalized in {"stopped", "cancelled", "canceled"}:
        return "terminal"
    if normalized == "starting":
        return "starting"
    if normalized in {"waiting", "waiting_input", "needs_input", "blocked", "queued"}:
        return "waiting"
    if normalized in {"asking", "question"}:
        return "asking"
    return "running"


def _liveness_for_status(status: str) -> str:
    lifecycle = _lifecycle_for_status(status)
    if lifecycle in {"starting", "running", "waiting", "asking"}:
        return "alive"
    return "dead"


def _display_status(status: str) -> str:
    return status.replace("-", " ").replace("_", " ").upper()


def _freshness(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized in {"fresh", "aging", "stale", "unknown"}:
        return normalized
    if normalized.startswith("cached"):
        return "stale"
    return "unknown"


def _connection_health(value: str) -> str:
    normalized = value.casefold().strip()
    if normalized in {"online", "degraded", "offline", "unknown"}:
        return normalized
    if normalized in {"reconnecting", "reconnect", "slow"}:
        return "degraded"
    return "unknown"


def _freshness_wire(
    value: str,
    *,
    observed_at_unix: float | None,
    partial: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "freshness": _freshness(value),
        "partial": partial,
        "refreshed_at_unix": observed_at_unix,
        "error": "partial" if partial else None,
    }


def _summary_with_host_observation(
    summary: dict[str, Any],
    *,
    freshness: str,
    connection_health: str,
    observed_at_unix: float | None,
) -> dict[str, Any]:
    summary["freshness"] = _freshness(freshness)
    summary["connection_health"] = _connection_health(connection_health)
    if observed_at_unix is not None:
        summary["observed_at_unix"] = observed_at_unix
    return summary


def _max_revision(summaries: Iterable[Mapping[str, Any]]) -> int | None:
    revisions: list[int] = []
    for summary in summaries:
        revision = summary.get("row_revision")
        if isinstance(revision, Mapping):
            value = revision.get("revision")
            if isinstance(value, int) and not isinstance(value, bool):
                revisions.append(value)
    return max(revisions) if revisions else None


def _max_observed_at_unix(summaries: Iterable[Mapping[str, Any]]) -> float | None:
    values: list[float] = []
    for summary in summaries:
        value = summary.get("observed_at_unix")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return max(values) if values else None


def _summary_counts_as_running(summary: Mapping[str, Any]) -> bool:
    if bool(summary.get("dismissable")):
        return False
    return str(summary.get("status_bucket") or "").casefold() == "running"


def _diagnostic(diagnostic: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    value = dict(diagnostic)
    value.setdefault("schema_version", 1)
    value.setdefault("alias", None)
    value.setdefault("operation", operation)
    return value


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
