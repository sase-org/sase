"""Federation config-loading tests.

Split from ``tests.test_dispatch_federation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.dispatch.federation as federation
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.models import CredentialRecord, MachineDiagnostic
from tests._dispatch_federation_helpers import installation_id
from tests.conftest import redirect_sase_home


def test_empty_remote_hosts_keep_facade_disabled_without_rust_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_binding(name: str) -> object:
        raise AssertionError(f"unexpected rust binding lookup: {name}")

    monkeypatch.setattr(federation._hosts, "require_rust_binding", fail_binding)

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "remote_hosts": [],
            }
        }
    )
    facade = federation.build_federation_facade(config)

    assert not config.enabled
    assert facade.health_sync()["status"] == "disabled"
    assert facade.summary_sync() == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "summary",
        "disabled": True,
        "hosts": [],
    }
    assert facade.attention_sync({"schema_version": 1, "logical_keys": []}) == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "attention",
        "disabled": True,
        "hosts": [],
    }
    assert facade.attention_inventory_sync({"schema_version": 1}) == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "attention_inventory",
        "disabled": True,
        "hosts": [],
    }
    with pytest.raises(
        federation.FederationWorkerUnavailable,
        match="no configured dispatch machines are available",
    ):
        facade.mutate_sync("apollo", {"schema_version": 1})
    with pytest.raises(
        federation.FederationWorkerUnavailable,
        match="no configured dispatch machines are available",
    ):
        facade.resolve_attention_sync("apollo", {"schema_version": 1})


def test_federation_worker_resolver_checks_active_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    worker = tmp_path / federation.FEDERATION_WORKER_COMMAND
    worker.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(federation._supervisor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        federation._supervisor.sys, "executable", str(tmp_path / "python")
    )

    assert federation.resolve_federation_worker_command() == (str(worker),)


def test_host_config_validates_plan_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        return {**plan, "endpoint": "https://fleet.example.test"}

    monkeypatch.setattr(
        federation._hosts, "require_rust_binding", lambda _name: validate
    )
    monkeypatch.setenv("SASE_FLEET_TOKEN", "secret-token")

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "remote_hosts": [
                    {
                        "alias": "workstation",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "env:SASE_FLEET_TOKEN",
                        "pinned_installation_id": "remote-install",
                    }
                ],
            }
        }
    )

    assert config.enabled
    assert config.hosts_wire()[0]["bearer_token"] == "secret-token"
    assert config.redacted_hosts()[0]["bearer_token"] == "<redacted>"


def test_machine_config_derives_federation_host_from_local_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pin = "sase_inst_v1_" + "a" * 64
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    LocalCredentialStore().put(
        CredentialRecord(
            ref="fleet:workstation",
            token="stored-token",
            token_type="bearer",
            provider_ref="builtin@https",
            endpoint="https://fleet.example.test/",
            installation_id=pin,
            scopes=("fleet.launch",),
        )
    )

    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        assert plan["provider_ref"] == "builtin:https"
        return {**plan, "endpoint": "https://fleet.example.test"}

    monkeypatch.setattr(
        federation._hosts, "require_rust_binding", lambda _name: validate
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path / ".sase")},
                "machines": {
                    "workstation": {
                        "provider": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "fleet:workstation",
                        "installation_pin": pin,
                    }
                },
            }
        }
    )

    assert config.enabled
    assert config.hosts_wire() == [
        {
            "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
            "alias": "workstation",
            "plan": {
                "provider_ref": "builtin:https",
                "endpoint": "https://fleet.example.test",
                "pinned_installation_id": pin,
                "connection_kind": "gateway",
                "schema_version": 1,
                "credential_ref": "fleet:workstation",
                "tls": {
                    "schema_version": 1,
                    "mode": "system_roots",
                    "ca_ref": None,
                    "server_name_ref": None,
                },
            },
            "bearer_token": "stored-token",
            "origin_installation_id": pin,
        }
    ]


def test_host_config_requires_env_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        federation._hosts,
        "require_rust_binding",
        lambda _name: lambda plan: {**plan, "credential_ref": "env:MISSING_TOKEN"},
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    with pytest.raises(federation.FederationConfigError, match="MISSING_TOKEN"):
        federation.load_federation_config(
            {
                "dispatch": {
                    "federation_worker": {"sase_home": str(tmp_path)},
                    "remote_hosts": [{"endpoint": "https://fleet.example.test"}],
                }
            }
        )


def test_dispatch_machines_resolve_local_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    machine_installation_id = installation_id("a")

    class Store:
        def get(self, ref: str) -> CredentialRecord | None:
            assert ref == "cred:workstation"
            return CredentialRecord(
                ref=ref,
                token="stored-secret",
                token_type="bearer",
                provider_ref="builtin@https",
                endpoint="https://fleet.example.test",
                installation_id=machine_installation_id,
            )

    monkeypatch.setattr(
        federation._hosts,
        "validate_connection_plan",
        lambda _machine, **kwargs: (),
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "machines": {
                    "workstation": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:workstation",
                        "pinned_installation_id": machine_installation_id,
                    }
                },
            }
        },
        credential_store=Store(),  # type: ignore[arg-type]
    )

    assert config.enabled
    assert config.diagnostics == ()
    wire = config.hosts_wire()[0]
    assert wire["alias"] == "workstation"
    assert wire["bearer_token"] == "stored-secret"
    assert wire["origin_installation_id"] == machine_installation_id
    assert config.redacted_hosts()[0]["bearer_token"] == "<redacted>"


def test_dispatch_machines_degrade_to_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Store:
        def get(self, _ref: str) -> CredentialRecord | None:
            return None

    monkeypatch.setattr(
        federation._hosts,
        "validate_connection_plan",
        lambda _machine, **kwargs: (
            MachineDiagnostic(
                code="invalid_connection_plan",
                alias="unused",
                severity="error",
                message="unused",
            ),
        ),
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "machines": {
                    "missing": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:missing",
                        "pinned_installation_id": installation_id("b"),
                    },
                    "quarantined": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:quarantined",
                        "pinned_installation_id": installation_id("c"),
                        "quarantined": True,
                        "quarantine_reason": "pin mismatch",
                    },
                },
            }
        },
        credential_store=Store(),  # type: ignore[arg-type]
    )

    assert not config.enabled
    assert config.hosts == ()
    codes = {diagnostic.code for diagnostic in config.diagnostics}
    assert {"credential_missing", "machine_quarantined"} <= codes
    disabled = federation.build_federation_facade(config).summary_sync()
    assert disabled["disabled"] is True
    assert {item["code"] for item in disabled["diagnostics"]} >= codes
