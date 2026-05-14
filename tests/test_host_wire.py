from __future__ import annotations

import pytest

from sase.host.wire import (
    HOST_CAP_IPC_V1,
    HOST_CAP_MANIFEST_V1,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    FakeInProcessHostTransport,
    host_request_from_dict,
    host_response_from_dict,
    host_wire_to_json_dict,
)


def _request_payload() -> dict[str, object]:
    return {
        "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        "request_id": "host_req_py",
        "deadline": {
            "timeout_ms": 30000,
            "deadline_unix_ms": None,
            "cancellation_token": "cancel_py",
            "future_deadline_field": "kept",
        },
        "actor": {
            "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            "actor_type": "test",
            "name": "pytest",
            "version": "0.1.0",
            "runtime": "python",
        },
        "operation": {
            "family": "xprompt",
            "operation": "xprompt.catalog",
        },
        "declared_capabilities": [HOST_CAP_IPC_V1, HOST_CAP_MANIFEST_V1],
        "workspace": {
            "project_id": "project-a",
            "project_dir": "/tmp/project-a",
            "workspace_dir": "/tmp/project-a",
            "changespec": None,
        },
        "environment": {
            "inherit": False,
            "allow": ["PATH"],
            "deny": ["OPENAI_API_KEY"],
            "required": [],
        },
        "manifest": None,
        "payload": {"limit": 10},
        "future_envelope_field": {"preserved": True},
    }


def test_host_request_decode_encode_preserves_unknown_fields() -> None:
    request = host_request_from_dict(_request_payload())

    encoded = host_wire_to_json_dict(request)

    assert encoded["future_envelope_field"] == {"preserved": True}
    assert encoded["deadline"]["future_deadline_field"] == "kept"
    assert encoded["operation"]["family"] == "xprompt"


def test_host_response_decode_encode_preserves_unknown_side_effect_fields() -> None:
    response = host_response_from_dict(
        {
            "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            "request_id": "host_req_py",
            "status": "ok",
            "result": {"entries": []},
            "error": None,
            "logs": [{"level": "info", "message": "loaded", "span_id": "s1"}],
            "duration_ms": 4,
            "resource_usage": {
                "wall_ms": 4,
                "cpu_ms": None,
                "peak_rss_bytes": None,
                "spawned_processes": 0,
                "network_requests": 0,
                "future_resource": 1,
            },
            "side_effects": [
                {
                    "type": "network_request",
                    "data": {"method": "GET", "url": "https://example.test"},
                    "future_intent": True,
                }
            ],
        }
    )

    encoded = host_wire_to_json_dict(response)

    assert encoded["logs"][0]["span_id"] == "s1"
    assert encoded["resource_usage"]["future_resource"] == 1
    assert encoded["side_effects"][0]["future_intent"] is True


def test_fake_in_process_transport_round_trips_request_id() -> None:
    transport = FakeInProcessHostTransport(
        lambda request: {"operation": request.operation.operation}
    )

    response = transport.request(_request_payload())

    assert response.request_id == "host_req_py"
    assert response.status == "ok"
    assert response.result == {"operation": "xprompt.catalog"}


def test_host_schema_mismatch_is_rejected() -> None:
    payload = _request_payload()
    payload["schema_version"] = 99

    with pytest.raises(ValueError, match="host IPC wire schema mismatch"):
        host_request_from_dict(payload)
