"""Federation facade and supervisor tests.

Split from ``tests.test_dispatch_federation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import sase.dispatch.federation as federation
from tests._dispatch_federation_helpers import installation_id
from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary


def test_supervisor_spawns_worker_and_replaces_config(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    argv: list[str] = []
    state = {"started": False}

    class Proc:
        def poll(self) -> int | None:
            return None

    class Client:
        def __init__(self, _path: Path, _max_frame_bytes: int) -> None:
            pass

        def request(
            self, operation: Mapping[str, Any], *, timeout_seconds: float
        ) -> dict[str, Any]:
            calls.append(dict(operation))
            if operation.get("op") == "health":
                if not state["started"]:
                    raise federation.FederationWorkerUnavailable("not ready")
                return {"schema_version": 1, "status": "ok"}
            if operation.get("op") == "replace_config":
                return {"schema_version": 1, "configured_hosts": 1}
            if operation.get("op") == "summary":
                return {"schema_version": 1, "hosts": [{"status": "ok"}]}
            raise AssertionError(f"unexpected operation: {operation}")

    def popen(command: list[str], **_kwargs: object) -> Proc:
        argv.extend(command)
        state["started"] = True
        return Proc()

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            command=("worker-bin",),
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
            idle_timeout_seconds=3,
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="remote",
                plan={
                    "provider_ref": "fleet",
                    "endpoint": "https://fleet.example.test",
                    "pinned_installation_id": "remote-install",
                },
                bearer_token="secret-token",
            ),
        ),
    )
    supervisor = federation.FederationWorkerSupervisor(
        config,
        client_factory=cast(federation.IpcClientFactory, Client),
        popen=cast(federation.PopenFactory, popen),
        sleep=lambda _seconds: None,
    )

    assert supervisor.request({"op": "summary"}, timeout_seconds=1)["hosts"] == [
        {"status": "ok"}
    ]
    assert argv[:1] == ["worker-bin"]
    assert "--sase-home" in argv
    assert str(tmp_path) in argv
    assert [call["op"] for call in calls] == [
        "health",
        "health",
        "health",
        "replace_config",
        "summary",
    ]
    assert calls[3]["hosts"][0]["bearer_token"] == "secret-token"


def test_facade_read_deadline_preserves_healthy_partial_host(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    healthy = fleet_summary(
        installation_id=installation_id("a"),
        agent_id="healthy",
    )
    worker_response = fleet_host_response(
        alias="apollo",
        installation_id=installation_id("a"),
        summaries=(healthy,),
        partial=True,
        operation="summary",
        diagnostics=(
            {
                "alias": "zeus",
                "operation": "summary",
                "code": "host_deadline_exceeded",
                "severity": "warning",
                "message": "zeus summary exceeded the read deadline",
            },
        ),
    )
    worker_response["configured_hosts"] = 2

    class Supervisor:
        def request(
            self,
            operation: Mapping[str, Any],
            *,
            timeout_seconds: float,
            retry: bool = True,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "operation": dict(operation),
                    "timeout_seconds": timeout_seconds,
                    "retry": retry,
                }
            )
            return json.loads(json.dumps(worker_response))

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
            request_timeout_seconds=5.0,
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="apollo",
                plan={"provider_ref": "fleet", "endpoint": "https://apollo.test"},
                bearer_token="secret-a",
                origin_installation_id=installation_id("a"),
            ),
            federation.FederationHostConfig(
                alias="zeus",
                plan={"provider_ref": "fleet", "endpoint": "https://zeus.test"},
                bearer_token="secret-b",
                origin_installation_id=installation_id("b"),
            ),
        ),
    )
    facade = federation.FederationFacade(
        config,
        supervisor=cast(federation.FederationWorkerSupervisor, Supervisor()),
    )

    response = facade.summary_sync(cache_only=False, timeout_seconds=0.125)

    assert calls == [
        {
            "operation": {"op": "summary", "cache_only": False},
            "timeout_seconds": 0.125,
            "retry": True,
        }
    ]
    assert response["partial"] is True
    assert response["configured_hosts"] == 2
    assert response["hosts"][0]["alias"] == "apollo"
    assert (
        response["hosts"][0]["payload"]["page"]["rows"][0]["logical_key"]
        == healthy["logical_key"]
    )
    assert response["diagnostics"][0]["code"] == "host_deadline_exceeded"


def test_facade_catalog_hosts_threads_per_host_queries(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class Supervisor:
        def request(
            self,
            operation: Mapping[str, Any],
            *,
            timeout_seconds: float,
            retry: bool = True,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "operation": dict(operation),
                    "timeout_seconds": timeout_seconds,
                    "retry": retry,
                }
            )
            return {
                "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
                "operation": "catalog",
                "hosts": [],
            }

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="apollo",
                plan={"provider_ref": "fleet", "endpoint": "https://apollo.test"},
                bearer_token="secret-a",
                origin_installation_id=installation_id("a"),
            ),
        ),
    )
    facade = federation.FederationFacade(
        config,
        supervisor=cast(federation.FederationWorkerSupervisor, Supervisor()),
    )

    response = facade.catalog_hosts_sync(
        (
            {
                "schema_version": 1,
                "installation_id": installation_id("a"),
                "query": {
                    "schema_version": 1,
                    "limit": 100,
                    "cursor": "a:100",
                    "include_terminal": True,
                },
            },
        ),
        timeout_seconds=0.25,
    )

    assert response["operation"] == "catalog"
    assert calls == [
        {
            "operation": {
                "op": "catalog_hosts",
                "queries": [
                    {
                        "schema_version": 1,
                        "installation_id": installation_id("a"),
                        "query": {
                            "schema_version": 1,
                            "limit": 100,
                            "cursor": "a:100",
                            "include_terminal": True,
                        },
                    }
                ],
                "cache_only": False,
            },
            "timeout_seconds": 0.25,
            "retry": True,
        }
    ]
