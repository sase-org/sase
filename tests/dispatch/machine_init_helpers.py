"""Shared helpers for machine-init tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.machine_init import MachineInitService
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    DiscoveryCandidate,
    DiscoveryResult,
    DispatchConfig,
    MachineRecord,
    ProviderSettings,
)


def _pin(hex_char: str = "a") -> str:
    return "sase_inst_v1_" + hex_char * 64


def _bundle(pin: str) -> str:
    return json.dumps(
        {
            "bootstrap_id": "boot-1",
            "bootstrap_secret": "one-time-secret",
            "pinned_installation_id": pin,
            "supported_protocol_versions": [1],
        }
    )


def _candidate(
    *,
    endpoint: str = "https://fleet.example.test",
    pin: str = "",
    display_name: str = "fleet",
    selector: str = "fleet",
    provider_ref: str = "builtin@https",
) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        provider_ref=provider_ref,
        endpoint=endpoint,
        display_name=display_name,
        machine_selector=selector,
        installation_pin=pin,
    )


def _record(
    *,
    alias: str = "apollo",
    endpoint: str = "https://apollo.example.test",
    pin: str = "",
    provider_ref: str = "builtin@https",
) -> MachineRecord:
    return MachineRecord(
        alias=alias,
        provider_ref=provider_ref,
        endpoint=endpoint,
        credential_ref=f"fleet:{alias}",
        pinned_installation_id=pin or _pin("a"),
    )


def _config(
    *,
    machines: tuple[MachineRecord, ...] = (),
    discovery: tuple[str, ...] = ("builtin@tailnet",),
) -> DispatchConfig:
    return DispatchConfig(
        providers={
            "builtin@https": ProviderSettings(ref="builtin@https", enabled=True),
            "builtin@tailnet": ProviderSettings(ref="builtin@tailnet", enabled=True),
        },
        machines=machines,
        discovery_enabled_provider_refs=discovery,
    )


class _FakeGateway:
    def __init__(
        self, pin: str, *, endpoint: str = "https://fleet.example.test"
    ) -> None:
        self.pin = pin
        self.endpoint = endpoint
        self.enroll_calls = 0
        self.hello_payload: dict[str, Any] = {
            "schema_version": 1,
            "installation": {"schema_version": 1, "installation_id": pin},
            "credential": {
                "schema_version": 1,
                "credential_id": "cred-1",
                "scopes": ["fleet.hello"],
                "issued_at_unix": 1.0,
                "expires_at_unix": None,
            },
            "capabilities": {
                "schema_version": 1,
                "host": ["fleet.hello"],
                "protocol": ["fleet.v1"],
                "resource": [],
            },
            "machine_selector": "fleet",
            "outcome": "enrolled",
            "protocol_version": 1,
            "quarantine": None,
            "token": "stored-token",
            "token_type": "bearer",
        }

    def enroll(self, **kwargs: object) -> dict[str, Any]:
        self.enroll_calls += 1
        assert kwargs["endpoint"] == self.endpoint
        return self.hello_payload

    def hello(self, **kwargs: object) -> dict[str, Any]:
        assert kwargs["endpoint"] == self.endpoint
        return self.hello_payload


def _service(
    isolated_dispatch: tuple[Path, Path],
    *,
    pin: str,
    candidates: tuple[DiscoveryCandidate, ...] = (),
    apply_fn: Any | None = None,
    use_chezmoi: bool = False,
    registry_target: Path | None = None,
) -> tuple[MachineInitService, _FakeGateway]:
    _config_dir, credential_path = isolated_dispatch
    fake = _FakeGateway(pin)
    machine = MachineService(
        credential_store=LocalCredentialStore(credential_path),
        gateway_client=fake,  # type: ignore[arg-type]
        discover_fn=lambda **_kwargs: candidates,
        discover_result_fn=lambda **_kwargs: DiscoveryResult(candidates=candidates),
    )
    service = MachineInitService(
        machine_service=machine,
        apply_chezmoi_fn=apply_fn,
        use_chezmoi_fn=lambda: use_chezmoi,
        registry_target_fn=(lambda: registry_target)
        if registry_target is not None
        else None,
    )
    return service, fake
