from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.dispatch.launch as launch
from sase.dispatch.models import DispatchConfig, MachineRecord, ProviderSettings
from tests.conftest import redirect_sase_home


def _pin(hex_char: str = "a") -> str:
    return "sase_inst_v1_" + hex_char * 64


def _machine() -> MachineRecord:
    return MachineRecord(
        alias="apollo",
        provider_ref="builtin@https",
        endpoint="https://fleet.example.test",
        credential_ref="fleet:apollo",
        pinned_installation_id=_pin(),
    )


def _config(machine: MachineRecord | None = None) -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True)
        },
        machines=(() if machine is None else (machine,)),
        request_timeout_seconds=5.0,
    )


def _rust_binding(name: str) -> Any:
    if name == "fleet_installation_identity_ensure":
        return lambda _home: {"record": {"installation_id": "source-install"}}
    if name == "fleet_launch_payload_fingerprint":
        return lambda _intent: {"schema_version": 1, "sha256": "a" * 64}
    if name == "fleet_validate_launch_request":
        return lambda request: request
    if name == "fleet_validate_launch_intent":
        return lambda intent: intent
    raise AssertionError(f"unexpected binding: {name}")


def test_dispatch_launch_submits_portable_request_and_records_follow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    machine = _machine()
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(launch, "load_dispatch_config", lambda: _config(machine))
    monkeypatch.setattr(launch, "require_rust_binding", _rust_binding)

    submitted: list[dict[str, Any]] = []

    class Facade:
        def launch_sync(
            self,
            target: str,
            request: dict[str, Any],
            *,
            timeout_seconds: float,
        ) -> dict[str, Any]:
            submitted.append(
                {
                    "target": target,
                    "request": request,
                    "timeout_seconds": timeout_seconds,
                }
            )
            return {
                "schema_version": 1,
                "operation": "launch",
                "hosts": [
                    {
                        "target": target,
                        "payload": {
                            "schema_version": 1,
                            "decision": "accept_new",
                            "reason": "accepted",
                            "receipt": {
                                "schema_version": 1,
                                "key": request["key"],
                                "payload_fingerprint": request["payload_fingerprint"],
                                "target_installation_id": machine.pinned_installation_id,
                                "accepted_at_unix_ms": 10,
                                "acceptance_expires_at_unix_ms": 20,
                                "state": "settled",
                                "logical_locator": {
                                    "schema_version": 1,
                                    "project": {
                                        "schema_version": 1,
                                        "origin": {
                                            "schema_version": 1,
                                            "installation_id": machine.pinned_installation_id,
                                        },
                                        "project_id": "sase",
                                    },
                                    "agent_id": request["intent"]["name"],
                                    "family_id": None,
                                },
                                "instance_locator": None,
                                "message": "launched",
                            },
                        },
                    }
                ],
            }

    monkeypatch.setattr(launch, "build_federation_facade", Facade)

    result = launch.maybe_dispatch_launch(
        "%dispatch:apollo do remote work",
        payload={"project": "sase", "patch_ref": "patch-123", "follow": True},
    )

    assert result is not None
    assert result.prompt == "do remote work"
    assert result.payload["dispatch"]["source_status"] == "settled"
    assert submitted[0]["target"] == "apollo"
    request = submitted[0]["request"]
    assert request["target_installation_id"] == machine.pinned_installation_id
    assert request["intent"]["prompt"] == "do remote work"
    assert request["intent"]["name"] == request["key"]["operation_id"]
    assert request["intent"]["project"]["patch_ref"] == "patch-123"
    assert request["intent"]["project"]["revision"] is None
    intent_store = tmp_path / ".sase" / "fleet" / "dispatch_launch_intents.json"
    assert '"status": "settled"' in intent_store.read_text(encoding="utf-8")
    follow_store = tmp_path / ".sase" / "fleet" / "follows.json"
    assert request["intent"]["name"] in follow_store.read_text(encoding="utf-8")


def test_dispatch_launch_rejects_local_only_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launch, "load_dispatch_config", lambda: _config(_machine()))

    with pytest.raises(
        launch.RemoteDispatchLaunchError,
        match="local-only run payload field 'launch_units'",
    ):
        launch.maybe_dispatch_launch(
            "%dispatch:apollo do it",
            payload={"launch_units": [{"kind": "agent"}]},
        )
