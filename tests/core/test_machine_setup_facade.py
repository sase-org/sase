"""Adapter contract tests for the published machine-setup core surface."""

from __future__ import annotations

from sase.core.machine_setup_facade import (
    classify_tailnet_discovery,
    classify_tailnet_health,
    reconcile_machine_enrollments,
)


def test_classify_tailnet_health_distinguishes_unrelated_from_legacy() -> None:
    unrelated = classify_tailnet_health(
        {
            "schema_version": 1,
            "alias": "web",
            "payload": {"status": "ok", "service": "unrelated"},
        }
    )
    legacy = classify_tailnet_health(
        {
            "schema_version": 1,
            "alias": "old-gateway",
            "payload": {"status": "ok"},
        }
    )
    assert unrelated["schema_version"] == 1
    assert unrelated["compatibility"] == "incompatible"
    assert unrelated["diagnostic"]["code"] == "tailnet_probe_unrelated_service"
    assert legacy["compatibility"] == "unknown"
    assert legacy["diagnostic"]["code"] == "tailnet_probe_fleet_unknown"


def test_classify_tailnet_discovery_never_infers_pin() -> None:
    result = classify_tailnet_discovery(
        {
            "schema_version": 1,
            "status": {
                "Self": {
                    "ID": "self-node",
                    "DNSName": "athena.tail297af1.ts.net.",
                },
                "Peer": {
                    "peer-apollo": {
                        "ID": "peer-apollo",
                        "DNSName": "apollo.tail297af1.ts.net.",
                        "HostName": "apollo",
                        "Online": True,
                        "OS": "linux",
                    }
                },
            },
            "health_observations": [
                {
                    "endpoint": "https://apollo.tail297af1.ts.net",
                    "payload": {
                        "status": "ok",
                        "fleet": {"supported_protocol_versions": [1]},
                    },
                }
            ],
        }
    )
    assert result["candidates"][0]["provider_ref"] == "builtin@tailnet"
    assert result["candidates"][0]["installation_pin"] == ""
    assert result["candidates"][0]["machine_selector"] == ""
    assert "compatibility=compatible" in result["candidates"][0]["detail"]


def test_reconcile_machine_enrollments_routes_pin_change_to_repair() -> None:
    pin_a = "sase_inst_v1_" + "a" * 64
    pin_b = "sase_inst_v1_" + "b" * 64
    result = reconcile_machine_enrollments(
        {
            "schema_version": 1,
            "candidates": [
                {
                    "provider_ref": "builtin@https",
                    "endpoint": "https://apollo.example.test",
                    "installation_pin": pin_b,
                }
            ],
            "enrolled": [
                {
                    "alias": "apollo",
                    "provider_ref": "builtin@https",
                    "endpoint": "https://apollo.example.test",
                    "pinned_installation_id": pin_a,
                }
            ],
        }
    )
    assert result["items"][0]["status"] == "repair"
    assert result["items"][0]["alias"] == "apollo"
    assert "sase machine repair apollo" in result["items"][0]["reason"]
