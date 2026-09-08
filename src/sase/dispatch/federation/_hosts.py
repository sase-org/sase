"""Federation host/config resolution: reading and validating ``dispatch`` config."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.config.core import load_merged_config
from sase.core.rust import require_rust_binding
from sase.dispatch.config import load_dispatch_config, validate_connection_plan
from sase.dispatch.credentials import CredentialStoreError, LocalCredentialStore
from sase.dispatch.models import CredentialRecord, MachineDiagnostic, MachineRecord

from ._constants import FEDERATION_IPC_SCHEMA_VERSION
from ._errors import FederationConfigError
from ._settings import FederationWorkerSettings, resolve_worker_settings


@dataclass(frozen=True)
class FederationHostConfig:
    """One remote fleet host plus its resolved bearer token."""

    alias: str | None
    plan: dict[str, Any]
    bearer_token: str
    origin_installation_id: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload = {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "alias": self.alias,
            "plan": dict(self.plan),
            "bearer_token": self.bearer_token,
        }
        if self.origin_installation_id:
            payload["origin_installation_id"] = self.origin_installation_id
        return payload

    def redacted(self) -> dict[str, Any]:
        payload = self.to_wire()
        payload["bearer_token"] = "<redacted>"
        return payload


@dataclass(frozen=True)
class FederationConfig:
    """Resolved federation facade configuration."""

    worker: FederationWorkerSettings
    hosts: tuple[FederationHostConfig, ...] = ()
    diagnostics: tuple[MachineDiagnostic, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.worker.enabled and bool(self.hosts)

    def hosts_wire(self) -> list[dict[str, Any]]:
        return [host.to_wire() for host in self.hosts]

    def redacted_hosts(self) -> list[dict[str, Any]]:
        return [host.redacted() for host in self.hosts]

    def diagnostics_wire(self) -> list[dict[str, Any]]:
        return [diagnostic_wire(diagnostic) for diagnostic in self.diagnostics]


def load_federation_config(
    raw_config: Mapping[str, Any] | None = None,
    *,
    credential_store: LocalCredentialStore | None = None,
) -> FederationConfig:
    """Read and validate ``dispatch`` federation configuration."""

    config = raw_config if raw_config is not None else load_merged_config()
    dispatch = _mapping(config.get("dispatch"))
    worker = resolve_worker_settings(_mapping(dispatch.get("federation_worker")))
    if not isinstance(raw_hosts := dispatch.get("remote_hosts"), list):
        raw_hosts = []
    if raw_hosts:
        legacy_hosts = _legacy_remote_host_configs(raw_hosts)
        return FederationConfig(worker=worker, hosts=legacy_hosts)

    dispatch_config = load_dispatch_config(config)
    diagnostics: list[MachineDiagnostic] = list(dispatch_config.diagnostics)
    if not dispatch_config.machines:
        return FederationConfig(worker=worker, diagnostics=tuple(diagnostics))

    store = credential_store or LocalCredentialStore()
    hosts: list[FederationHostConfig] = []
    for machine in dispatch_config.machines:
        host, host_diagnostics = _machine_host_config(machine, store, dispatch_config)
        diagnostics.extend(host_diagnostics)
        if host is not None:
            hosts.append(host)
    return FederationConfig(
        worker=worker,
        hosts=tuple(hosts),
        diagnostics=tuple(diagnostics),
    )


def diagnostic_wire(diagnostic: MachineDiagnostic) -> dict[str, Any]:
    payload = {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "severity": diagnostic.severity,
    }
    if diagnostic.alias:
        payload["alias"] = diagnostic.alias
    return payload


def _host_config(raw: Mapping[str, Any], index: int) -> FederationHostConfig:
    plan = _validate_plan(_connection_plan(raw), f"dispatch.remote_hosts[{index}]")
    credential_ref = str(plan.get("credential_ref") or "")
    bearer_token = _resolve_env_credential(credential_ref, index)
    alias = raw.get("alias")
    return FederationHostConfig(
        alias=alias.strip() if isinstance(alias, str) and alias.strip() else None,
        plan=plan,
        bearer_token=bearer_token,
    )


def _legacy_remote_host_configs(
    raw_hosts: Sequence[object],
) -> tuple[FederationHostConfig, ...]:
    hosts: list[FederationHostConfig] = []
    for index, raw_host in enumerate(raw_hosts):
        if not isinstance(raw_host, Mapping):
            raise FederationConfigError(
                f"dispatch.remote_hosts[{index}] must be an object"
            )
        if raw_host.get("enabled", True) is False:
            continue
        hosts.append(_host_config(raw_host, index))
    return tuple(hosts)


def _validate_plan(plan: Mapping[str, Any], label: str) -> dict[str, Any]:
    validate = require_rust_binding("fleet_validate_connection_plan")
    try:
        validated = validate(dict(plan))
    except Exception as exc:
        raise FederationConfigError(
            f"{label} has an invalid connection plan: {exc}"
        ) from exc
    if not isinstance(validated, dict):
        raise FederationConfigError(f"{label} validation returned a non-object plan")
    return validated


def _rust_connection_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(plan)
    payload["provider_ref"] = str(payload.get("provider_ref") or "").replace("@", ":")
    return payload


def _machine_host_config(
    machine: MachineRecord,
    store: LocalCredentialStore,
    config: Any,
) -> tuple[FederationHostConfig | None, tuple[MachineDiagnostic, ...]]:
    diagnostics: list[MachineDiagnostic] = []
    if machine.quarantined:
        diagnostics.append(
            MachineDiagnostic(
                code="machine_quarantined",
                alias=machine.alias,
                severity="warning",
                message=(
                    machine.quarantine_reason
                    or f"dispatch machine {machine.alias} is quarantined"
                ),
            )
        )
        return None, tuple(diagnostics)

    try:
        credential = store.get(machine.credential_ref)
    except CredentialStoreError as exc:
        diagnostics.append(
            MachineDiagnostic(
                code="credential_store_unreadable",
                alias=machine.alias,
                severity="error",
                message=f"credential store is unreadable: {exc}",
            )
        )
        return None, tuple(diagnostics)
    if credential is None:
        diagnostics.append(
            MachineDiagnostic(
                code="credential_missing",
                alias=machine.alias,
                severity="error",
                message=(
                    f"credential ref {machine.credential_ref} is missing from "
                    "the local store"
                ),
            )
        )
        return None, tuple(diagnostics)

    diagnostics.extend(_credential_machine_diagnostics(machine, credential))
    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return None, tuple(diagnostics)

    try:
        from sase.dispatch.providers import connection_plan_for_machine

        plan = connection_plan_for_machine(machine, config=config)
    except Exception as exc:  # noqa: BLE001 - provider boundary.
        diagnostics.append(
            MachineDiagnostic(
                code="connection_plan_failed",
                alias=machine.alias,
                severity="error",
                message=(
                    f"connection plan for {machine.alias} could not be resolved: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        )
        return None, tuple(diagnostics)

    diagnostics.extend(validate_connection_plan(machine, config=config, plan=plan))
    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return None, tuple(diagnostics)

    return (
        FederationHostConfig(
            alias=machine.alias,
            plan=_rust_connection_plan(plan),
            bearer_token=credential.token,
            origin_installation_id=credential.installation_id,
        ),
        tuple(diagnostics),
    )


def _credential_machine_diagnostics(
    machine: MachineRecord,
    credential: CredentialRecord,
) -> tuple[MachineDiagnostic, ...]:
    diagnostics: list[MachineDiagnostic] = []
    if credential.installation_id != machine.pinned_installation_id:
        diagnostics.append(
            MachineDiagnostic(
                code="credential_installation_mismatch",
                alias=machine.alias,
                severity="error",
                message=(
                    f"credential {credential.ref} belongs to "
                    f"{credential.installation_id}, not "
                    f"{machine.pinned_installation_id}"
                ),
            )
        )
    if credential.provider_ref != machine.provider_ref:
        diagnostics.append(
            MachineDiagnostic(
                code="credential_provider_mismatch",
                alias=machine.alias,
                severity="error",
                message=(
                    f"credential {credential.ref} provider "
                    f"{credential.provider_ref!r} does not match "
                    f"{machine.provider_ref!r}"
                ),
            )
        )
    if credential.endpoint.rstrip("/") != machine.endpoint.rstrip("/"):
        diagnostics.append(
            MachineDiagnostic(
                code="credential_endpoint_mismatch",
                alias=machine.alias,
                severity="error",
                message=(
                    f"credential {credential.ref} endpoint does not match "
                    f"dispatch.machines.{machine.alias}.endpoint"
                ),
            )
        )
    return tuple(diagnostics)


def _connection_plan(raw: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw.get("plan"), Mapping):
        plan = dict(raw["plan"])
    else:
        plan = {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "provider_ref": raw.get("provider_ref", "fleet"),
            "endpoint": raw.get("endpoint", ""),
            "credential_ref": raw.get("credential_ref", ""),
            "pinned_installation_id": raw.get("pinned_installation_id", ""),
            "connection_kind": raw.get("connection_kind", "gateway"),
            "tls": raw.get("tls")
            or {
                "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
                "mode": "system_roots",
                "ca_ref": None,
                "server_name_ref": None,
            },
        }
    return plan


def _resolve_env_credential(credential_ref: str, index: int) -> str:
    prefix, _, name = credential_ref.partition(":")
    if prefix != "env" or not name:
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] credential_ref must use env:NAME"
        )
    token = os.environ.get(name)
    if not token:
        raise FederationConfigError(
            f"dispatch.remote_hosts[{index}] credential {credential_ref!r} is missing"
        )
    return token


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
