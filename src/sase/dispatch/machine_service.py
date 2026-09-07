"""Service layer for enrolled remote-machine operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import base64
import json
import platform
import time
import uuid
from typing import Any

import yaml  # type: ignore[import-untyped]

import sase

from .config import (
    load_dispatch_config,
    remove_machine_record,
    rename_machine_record,
    require_remote_dispatch_enabled,
    validate_connection_plan,
    write_machine_record,
)
from .credentials import LocalCredentialStore
from .fleet_client import (
    FleetGatewayClient,
    FleetGatewayError,
    enrollment_result_from_response,
)
from .models import (
    BootstrapBundle,
    DiscoveryCandidate,
    EnrollmentBundleError,
    EnrollmentResult,
    FLEET_PROTOCOL_VERSION,
    MachineRecord,
    MachineRegistryError,
    MachineStatus,
    is_installation_id,
    validate_machine_alias,
)
from .providers import discover_dispatch_candidates

InputFunc = Callable[[str], str]


class MachineService:
    """High-level operations for the ``sase machine`` command surface."""

    def __init__(
        self,
        *,
        credential_store: LocalCredentialStore | None = None,
        gateway_client: FleetGatewayClient | None = None,
        discover_fn: Callable[..., tuple[DiscoveryCandidate, ...]] | None = None,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.credential_store = credential_store or LocalCredentialStore()
        self.gateway_client = gateway_client or FleetGatewayClient()
        self.discover_fn = discover_fn or discover_dispatch_candidates
        self.time_fn = time_fn

    def list_machines(self) -> tuple[MachineRecord, ...]:
        """Return configured machine records without provider discovery."""
        return load_dispatch_config().machines

    def discover(
        self,
        *,
        provider_refs: Sequence[str] = (),
        timeout_seconds: float | None = None,
    ) -> tuple[DiscoveryCandidate, ...]:
        require_remote_dispatch_enabled()
        config = load_dispatch_config()
        return self.discover_fn(
            config=config,
            provider_refs=tuple(provider_refs),
            timeout_seconds=timeout_seconds,
        )

    def add_machine(
        self,
        *,
        alias: str,
        endpoint: str,
        provider_ref: str,
        bundle_text: str,
        timeout_seconds: float | None = None,
    ) -> EnrollmentResult:
        require_remote_dispatch_enabled()
        validate_machine_alias(alias)
        config = load_dispatch_config()
        if alias in config.machine_by_alias():
            raise MachineRegistryError(f"machine alias already exists: {alias}")
        if not config.provider_enabled(provider_ref):
            raise MachineRegistryError(
                f"dispatch provider is not enabled: {provider_ref}"
            )
        bundle = _parse_enrollment_bundle(bundle_text)
        if not is_installation_id(bundle.pinned_installation_id):
            raise EnrollmentBundleError("enrollment bundle installation pin is invalid")

        credential_ref = _credential_ref_for_alias(alias)
        record = MachineRecord(
            alias=alias,
            provider_ref=provider_ref,
            endpoint=endpoint,
            credential_ref=credential_ref,
            pinned_installation_id=bundle.pinned_installation_id,
        )
        diagnostics = validate_connection_plan(record)
        errors = [item.message for item in diagnostics if item.severity == "error"]
        if errors:
            raise MachineRegistryError(errors[0])

        client = self._client(timeout_seconds)
        payload = client.enroll(
            endpoint=endpoint,
            bundle=bundle,
            controller=_controller_metadata(),
            requested_scopes=bundle.requested_scopes,
        )
        result, credential = enrollment_result_from_response(
            alias=alias,
            credential_ref=credential_ref,
            provider_ref=provider_ref,
            endpoint=endpoint,
            payload=payload,
        )
        if result.installation_id != bundle.pinned_installation_id:
            raise MachineRegistryError(
                "gateway installation identity did not match the enrollment pin"
            )
        if result.quarantined:
            quarantined = replace(
                record,
                quarantined=True,
                quarantine_reason=result.quarantine_reason or "quarantined",
            )
            write_machine_record(quarantined)
            return replace(result, record=quarantined)
        if credential is None:
            raise MachineRegistryError("gateway enrollment did not return credentials")
        if result.protocol_version != FLEET_PROTOCOL_VERSION:
            raise MachineRegistryError(
                "gateway selected an unsupported protocol version"
            )

        self.credential_store.put(credential)
        try:
            write_machine_record(record)
        except Exception:
            self.credential_store.delete(credential.ref)
            raise
        return replace(result, record=record)

    def remove_machine(self, alias: str) -> MachineRecord:
        config = load_dispatch_config()
        record = _record_or_raise(config.machine_by_alias(), alias)
        remove_machine_record(alias)
        self.credential_store.delete(record.credential_ref)
        return record

    def rename_machine(self, old_alias: str, new_alias: str) -> MachineRecord:
        validate_machine_alias(new_alias)
        config = load_dispatch_config()
        by_alias = config.machine_by_alias()
        record = _record_or_raise(by_alias, old_alias)
        if new_alias in by_alias:
            raise MachineRegistryError(f"machine alias already exists: {new_alias}")
        renamed = replace(record, alias=new_alias)
        rename_machine_record(old_alias, renamed)
        return renamed

    def repair_machine(
        self,
        *,
        alias: str,
        bundle_text: str,
        timeout_seconds: float | None = None,
    ) -> EnrollmentResult:
        require_remote_dispatch_enabled()
        config = load_dispatch_config()
        existing = _record_or_raise(config.machine_by_alias(), alias)
        bundle = _parse_enrollment_bundle(bundle_text)
        if not is_installation_id(bundle.pinned_installation_id):
            raise EnrollmentBundleError("enrollment bundle installation pin is invalid")
        credential_ref = _credential_ref_for_alias(alias, rotate=True)
        repaired = replace(
            existing,
            credential_ref=credential_ref,
            pinned_installation_id=bundle.pinned_installation_id,
            quarantined=False,
            quarantine_reason="",
        )
        diagnostics = validate_connection_plan(repaired)
        errors = [item.message for item in diagnostics if item.severity == "error"]
        if errors:
            raise MachineRegistryError(errors[0])

        client = self._client(timeout_seconds)
        payload = client.enroll(
            endpoint=existing.endpoint,
            bundle=bundle,
            controller=_controller_metadata(),
            requested_scopes=bundle.requested_scopes,
        )
        result, credential = enrollment_result_from_response(
            alias=alias,
            credential_ref=credential_ref,
            provider_ref=existing.provider_ref,
            endpoint=existing.endpoint,
            payload=payload,
        )
        if result.installation_id != bundle.pinned_installation_id:
            raise MachineRegistryError(
                "gateway installation identity did not match the enrollment pin"
            )
        if result.quarantined:
            repaired = replace(
                existing,
                credential_ref=credential_ref,
                pinned_installation_id=bundle.pinned_installation_id,
                quarantined=True,
                quarantine_reason=result.quarantine_reason or "quarantined",
            )
            write_machine_record(repaired)
            return replace(result, record=repaired)
        if credential is None:
            raise MachineRegistryError("gateway repair did not return credentials")
        if result.protocol_version != FLEET_PROTOCOL_VERSION:
            raise MachineRegistryError(
                "gateway selected an unsupported protocol version"
            )

        self.credential_store.put(credential)
        try:
            write_machine_record(repaired)
        except Exception:
            self.credential_store.delete(credential.ref)
            raise
        if existing.credential_ref != credential.ref:
            self.credential_store.delete(existing.credential_ref)
        return replace(result, record=repaired)

    def status(
        self,
        aliases: Sequence[str] = (),
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[MachineStatus, ...]:
        require_remote_dispatch_enabled()
        config = load_dispatch_config()
        by_alias = config.machine_by_alias()
        selected = tuple(aliases) or tuple(sorted(by_alias))
        statuses: list[MachineStatus] = []
        client = self._client(timeout_seconds)
        for alias in selected:
            record = by_alias.get(alias)
            if record is None:
                statuses.append(
                    MachineStatus(
                        alias=alias,
                        state="error",
                        provider_ref="",
                        endpoint="",
                        message="machine alias is not configured",
                    )
                )
                continue
            if record.quarantined:
                statuses.append(
                    MachineStatus(
                        alias=alias,
                        state="quarantined",
                        provider_ref=record.provider_ref,
                        endpoint=record.endpoint,
                        installation_id=record.pinned_installation_id,
                        message=record.quarantine_reason or "installation quarantined",
                    )
                )
                continue
            credential = self.credential_store.get(record.credential_ref)
            if credential is None:
                statuses.append(
                    MachineStatus(
                        alias=alias,
                        state="error",
                        provider_ref=record.provider_ref,
                        endpoint=record.endpoint,
                        installation_id=record.pinned_installation_id,
                        message="local credential ref is missing",
                    )
                )
                continue
            try:
                payload = client.hello(endpoint=record.endpoint, credential=credential)
                status = _status_from_hello(record, payload)
                if status.state == "quarantined":
                    write_machine_record(
                        replace(
                            record,
                            quarantined=True,
                            quarantine_reason=status.message,
                        )
                    )
            except FleetGatewayError as exc:
                status = MachineStatus(
                    alias=alias,
                    state="error",
                    provider_ref=record.provider_ref,
                    endpoint=record.endpoint,
                    installation_id=record.pinned_installation_id,
                    message=f"hello failed: {exc.code}",
                )
            statuses.append(status)
        return tuple(statuses)

    def _client(self, timeout_seconds: float | None) -> FleetGatewayClient:
        if timeout_seconds is None:
            return self.gateway_client
        return FleetGatewayClient(
            timeout_seconds=timeout_seconds,
            opener=getattr(self.gateway_client, "opener", None),
            max_response_bytes=getattr(
                self.gateway_client,
                "max_response_bytes",
                64 * 1024,
            ),
        )


def _parse_enrollment_bundle(text: str) -> BootstrapBundle:
    """Parse JSON, YAML, or base64-encoded JSON enrollment bundle text."""
    payload = _parse_bundle_payload(text)
    bootstrap_id = _string_field(payload, "bootstrap_id")
    bootstrap_secret = _string_field(payload, "bootstrap_secret")
    pinned = _string_field(
        payload,
        "pinned_installation_id",
        fallback="installation_pin",
    )
    protocols = _int_tuple(
        payload.get("supported_protocol_versions", payload.get("protocol_versions")),
        default=(FLEET_PROTOCOL_VERSION,),
    )
    scopes = tuple(
        str(item)
        for item in payload.get("requested_scopes", ())
        if isinstance(item, str) and item
    )
    return BootstrapBundle(
        bootstrap_id=bootstrap_id,
        bootstrap_secret=bootstrap_secret,
        pinned_installation_id=pinned,
        supported_protocol_versions=protocols,
        requested_scopes=scopes,
    )


def _credential_ref_for_alias(alias: str, *, rotate: bool = False) -> str:
    validate_machine_alias(alias)
    if not rotate:
        return f"fleet:{alias}"
    return f"fleet:{alias}:{uuid.uuid4().hex[:8]}"


def _parse_bundle_payload(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise EnrollmentBundleError("enrollment bundle is empty")
    candidates = [stripped]
    try:
        decoded = base64.urlsafe_b64decode(_pad_base64(stripped)).decode("utf-8")
        candidates.append(decoded.strip())
    except Exception:
        pass
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            try:
                payload = yaml.safe_load(candidate)
            except Exception:
                payload = None
        if isinstance(payload, Mapping):
            return payload
    raise EnrollmentBundleError("enrollment bundle must be a mapping")


def _pad_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return f"{value}{padding}".encode("ascii")


def _string_field(
    payload: Mapping[str, Any],
    name: str,
    *,
    fallback: str | None = None,
) -> str:
    value = payload.get(name)
    if value is None and fallback is not None:
        value = payload.get(fallback)
    if not isinstance(value, str) or not value:
        raise EnrollmentBundleError(f"enrollment bundle is missing {name}")
    return value


def _int_tuple(value: object, *, default: tuple[int, ...]) -> tuple[int, ...]:
    if value is None:
        return default
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EnrollmentBundleError("supported_protocol_versions must be a list")
    ints = tuple(int(item) for item in value if isinstance(item, int))
    return ints or default


def _controller_metadata() -> dict[str, object]:
    return {
        "app_version": getattr(sase, "__version__", ""),
        "controller_id": None,
        "display_name": platform.node() or None,
        "platform": platform.platform() or None,
    }


def _record_or_raise(
    by_alias: Mapping[str, MachineRecord],
    alias: str,
) -> MachineRecord:
    try:
        return by_alias[alias]
    except KeyError as exc:
        raise MachineRegistryError(f"machine alias is not configured: {alias}") from exc


def _status_from_hello(
    record: MachineRecord,
    payload: Mapping[str, Any],
) -> MachineStatus:
    installation = payload.get("installation")
    if payload.get("schema_version") != 1:
        return _hello_error(record, "hello response schema version is unsupported")
    if not isinstance(installation, Mapping):
        return _identity_error(record, "hello response did not include installation")
    installation_id = installation.get("installation_id")
    if installation_id != record.pinned_installation_id:
        return _identity_error(record, "hello installation identity mismatch")
    capabilities = payload.get("capabilities")
    protocol = payload.get("protocol_version")
    if protocol != FLEET_PROTOCOL_VERSION:
        return _hello_error(record, "hello response protocol version is unsupported")
    if not _valid_capabilities(capabilities):
        return _hello_error(record, "hello response capabilities are invalid")
    machine_selector = payload.get("machine_selector")
    return MachineStatus(
        alias=record.alias,
        state="ok",
        provider_ref=record.provider_ref,
        endpoint=record.endpoint,
        machine_selector=machine_selector if isinstance(machine_selector, str) else "",
        installation_id=record.pinned_installation_id,
        protocol_version=protocol if isinstance(protocol, int) else None,
        capabilities=_capability_mapping(capabilities),
        message="hello ok",
    )


def _identity_error(record: MachineRecord, message: str) -> MachineStatus:
    return MachineStatus(
        alias=record.alias,
        state="quarantined",
        provider_ref=record.provider_ref,
        endpoint=record.endpoint,
        installation_id=record.pinned_installation_id,
        message=message,
    )


def _hello_error(record: MachineRecord, message: str) -> MachineStatus:
    return MachineStatus(
        alias=record.alias,
        state="error",
        provider_ref=record.provider_ref,
        endpoint=record.endpoint,
        installation_id=record.pinned_installation_id,
        message=message,
    )


def _valid_capabilities(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    protocol_caps = value.get("protocol")
    return isinstance(protocol_caps, list) and "fleet.v1" in protocol_caps


def _capability_mapping(value: object) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): tuple(str(item) for item in items if isinstance(item, str))
        for key, items in value.items()
        if isinstance(items, list)
    }


__all__ = [
    "MachineService",
]
