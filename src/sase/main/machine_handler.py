"""Handler for ``sase machine`` commands."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Mapping
import getpass
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from sase.core.time import format_local
from sase.dispatch.config import load_dispatch_config
from sase.dispatch.fleet_client import FleetGatewayError
from sase.dispatch.machine_init import MachineInitService
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    BootstrapIssueResult,
    DispatchError,
    DiscoveryCandidate,
    EnrollmentResult,
    GatewayServiceVersion,
    MachineDiagnostic,
    MachineRecord,
    MachineStatus,
)
from sase.uv_tool.versions import collect_installed_core_versions
from sase.version.inventory import CORE_DISTRIBUTION_NAME, HOST_DISTRIBUTION_NAME


def handle_machine_command(args: argparse.Namespace) -> int:
    service = MachineService()
    subcommand = getattr(args, "machine_subcommand", "list")
    try:
        if subcommand == "add":
            return _handle_add(args, service)
        if subcommand == "agent":
            from sase.ops.commands.machine import handle_machine_agent_command

            return handle_machine_agent_command(args)
        if subcommand == "attention":
            from sase.ops.commands.machine_attention import (
                handle_machine_attention_command,
            )

            return handle_machine_attention_command(args)
        if subcommand == "bootstrap":
            return _handle_bootstrap(args, service)
        if subcommand == "discover":
            return _handle_discover(args, service)
        if subcommand == "init":
            from .init_machine_handler import run_init_machine

            return run_init_machine(args)
        if subcommand == "list":
            return _handle_list(args)
        if subcommand == "remove":
            return _handle_remove(args, service)
        if subcommand == "rename":
            return _handle_rename(args, service)
        if subcommand == "repair":
            return _handle_repair(args, service)
        if subcommand == "show":
            return _handle_show(args)
        if subcommand == "status":
            return _handle_status(args, service)
    except (DispatchError, FleetGatewayError, OSError) as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "command": "machine",
                        "subcommand": subcommand,
                        "ok": False,
                        "error": _safe_error(exc),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"sase machine {subcommand}: {_safe_error(exc)}", file=sys.stderr)
        return 1
    return 1


def _handle_bootstrap(args: argparse.Namespace, service: MachineService) -> int:
    result = service.issue_bootstrap(
        expires_seconds=getattr(args, "expires", None),
        scopes=tuple(getattr(args, "scope", None) or ()),
    )
    bundle_json = _bootstrap_bundlemachine_json_document(result)
    if getattr(args, "json", False):
        print(bundle_json)
    else:
        _print_bootstrap_summary(result)
        print(_base64url(bundle_json))
    return 0


def _handle_add(args: argparse.Namespace, service: MachineService) -> int:
    provider_ref, endpoint = _resolve_provider_endpoint(args)
    if not endpoint:
        raise DispatchError("an HTTPS endpoint or candidate key is required")
    result = service.add_machine(
        alias=args.alias,
        endpoint=endpoint,
        provider_ref=provider_ref,
        bundle_text=read_enrollment_bundle(args),
        ssh_target=str(getattr(args, "ssh_target", "") or ""),
        timeout_seconds=getattr(args, "timeout", None),
    )
    return _activate_and_report(args, service, result, success_verb="enrolled")


def _handle_discover(args: argparse.Namespace, service: MachineService) -> int:
    result = service.discover_detailed(
        provider_refs=tuple(getattr(args, "provider", None) or ()),
        timeout_seconds=getattr(args, "timeout", None),
    )
    candidates = result.candidates
    if getattr(args, "json", False):
        print(
            machine_json_document(
                {
                    "candidates": [_candidate_row(item) for item in candidates],
                    "diagnostics": [
                        _diagnostic_row(item) for item in result.diagnostics
                    ],
                }
            )
        )
    elif not candidates:
        print("No remote machine candidates found.")
    else:
        for candidate in candidates:
            label = candidate.display_name or candidate.endpoint
            detail = f"\t{candidate.detail}" if candidate.detail else ""
            print(f"{candidate.key}\t{label}{detail}")
    if not getattr(args, "json", False):
        for diagnostic in result.diagnostics:
            print(
                (
                    f"{diagnostic.severity}: {diagnostic.message}"
                    if not diagnostic.alias
                    else (
                        f"{diagnostic.severity}: {diagnostic.alias}: "
                        f"{diagnostic.message}"
                    )
                ),
                file=sys.stderr,
            )
    return 1 if any(item.severity == "error" for item in result.diagnostics) else 0


def _handle_list(args: argparse.Namespace) -> int:
    config = load_dispatch_config()
    if getattr(args, "json", False):
        print(
            machine_json_document(
                {
                    "machines": [_machine_row(machine) for machine in config.machines],
                    "diagnostics": [
                        {
                            "code": item.code,
                            "severity": item.severity,
                            "message": item.message,
                            "alias": item.alias,
                        }
                        for item in config.diagnostics
                    ],
                }
            )
        )
    elif not config.machines:
        print("No remote machines are configured.")
    else:
        for machine in config.machines:
            state = "quarantined" if machine.quarantined else "configured"
            print(
                f"{machine.alias}\t{state}\t{machine.provider_ref}\t"
                f"{machine.endpoint}\tssh={machine.effective_ssh_target}"
            )
    return 1 if any(item.severity == "error" for item in config.diagnostics) else 0


def _handle_show(args: argparse.Namespace) -> int:
    config = load_dispatch_config()
    alias = str(getattr(args, "alias", "") or "")
    record = config.machine_by_alias().get(alias)
    if record is None:
        raise DispatchError(f"machine alias is not configured: {alias}")
    payload = _machine_row(record)
    if getattr(args, "json", False):
        print(machine_json_document({"machine": payload}))
    else:
        for key in sorted(payload):
            print(f"{key}\t{payload[key]}")
    return 0


def _handle_remove(args: argparse.Namespace, service: MachineService) -> int:
    if not getattr(args, "yes", False) and sys.stdin.isatty():
        answer = input(f"Remove remote machine alias '{args.alias}'? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1
    record = service.remove_machine(args.alias)
    if getattr(args, "json", False):
        print(machine_json_document({"removed": _machine_row(record)}))
    else:
        print(f"Removed remote machine alias {record.alias}.")
    return 0


def _handle_rename(args: argparse.Namespace, service: MachineService) -> int:
    record = service.rename_machine(args.old_alias, args.new_alias)
    if getattr(args, "json", False):
        print(machine_json_document({"renamed": _machine_row(record)}))
    else:
        print(f"Renamed remote machine alias {args.old_alias} to {record.alias}.")
    return 0


def _handle_repair(args: argparse.Namespace, service: MachineService) -> int:
    existing = load_dispatch_config().machine_by_alias().get(args.alias)
    previous_ref = existing.credential_ref if existing is not None else ""
    result = service.repair_machine(
        alias=args.alias,
        bundle_text=read_enrollment_bundle(args),
        timeout_seconds=getattr(args, "timeout", None),
    )
    code = _activate_and_report(args, service, result, success_verb="repaired")
    if (
        code == 0
        and not result.quarantined
        and previous_ref
        and previous_ref != result.credential_ref
    ):
        service.credential_store.delete(previous_ref)
    return code


def _activate_and_report(
    args: argparse.Namespace,
    service: MachineService,
    result: EnrollmentResult,
    *,
    success_verb: str,
) -> int:
    activation = MachineInitService(machine_service=service).activate(
        alias=result.alias,
        expected=result,
        timeout_seconds=getattr(args, "timeout", None),
    )
    activated = activation.ok and not result.quarantined
    if getattr(args, "json", False):
        print(
            machine_json_document(
                {
                    "result": enrollment_result_row(result),
                    "recovery": (
                        [activation.recovery_message]
                        if activation.recovery_message
                        else []
                    ),
                    "errors": list(activation.errors),
                    "activated": activated,
                    "chezmoi_proc_id": activation.proc_id or None,
                    "chezmoi_in_progress": activation.in_progress,
                }
            )
        )
    else:
        for message in activation.errors:
            print(f"error: {message}", file=sys.stderr)
        if activation.recovery_message:
            print(activation.recovery_message, file=sys.stderr)
        if result.quarantined:
            print(
                f"{result.alias}: quarantined as "
                f"{result.machine_selector or 'remote machine'}"
            )
        elif activation.ok:
            if success_verb == "repaired":
                print(f"{result.alias}: repaired")
            else:
                print(
                    f"{result.alias}: {success_verb} as "
                    f"{result.machine_selector or 'remote machine'}"
                )
    return 0 if activated else 1


def _handle_status(args: argparse.Namespace, service: MachineService) -> int:
    statuses = service.status(
        tuple(getattr(args, "aliases", ()) or ()),
        timeout_seconds=getattr(args, "timeout", None),
    )
    local = _local_status_versions()
    if getattr(args, "json", False):
        print(
            machine_json_document(
                {"statuses": [_status_row(status, local=local) for status in statuses]}
            )
        )
    else:
        for status in statuses:
            print(f"{status.alias}\t{status.state}\t{_status_message(status, local)}")
    return 0 if all(status.ok for status in statuses) else 1


def _resolve_provider_endpoint(args: argparse.Namespace) -> tuple[str, str]:
    provider = getattr(args, "provider", None) or "builtin@https"
    endpoint = getattr(args, "endpoint", None) or ""
    candidate = getattr(args, "candidate", None) or ""
    if candidate and not endpoint:
        try:
            provider, endpoint = candidate.split("|", 1)
        except ValueError as exc:
            raise DispatchError(
                "candidate key must be formatted as PROVIDER|ENDPOINT"
            ) from exc
    return provider, endpoint


def read_enrollment_bundle(
    args: argparse.Namespace,
    *,
    stdin: TextIO | None = None,
    getpass_func: Callable[[str], str] | None = None,
) -> str:
    """Read an enrollment bundle from file, stdin, or a hidden prompt.

    Never uses echoing ``input()``. Secrets are accepted from
    ``-B/--bootstrap-file``, piped stdin, or ``getpass``.
    """
    path = getattr(args, "bootstrap_file", None)
    if path:
        return Path(path).read_text(encoding="utf-8")
    stream = stdin if stdin is not None else sys.stdin
    if not stream.isatty():
        return stream.read()
    prompt = getpass_func or getpass.getpass
    return prompt("Paste enrollment bundle: ")


def machine_json_document(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "command": "machine",
            **payload,
        },
        indent=2,
        sort_keys=True,
    )


def _bootstrap_bundlemachine_json_document(result: BootstrapIssueResult) -> str:
    return json.dumps(result.bundle, sort_keys=True)


def _base64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _print_bootstrap_summary(result: BootstrapIssueResult) -> None:
    scopes = (
        ", ".join(result.requested_scopes) if result.requested_scopes else "(default)"
    )
    print("Issued target-local SASE enrollment bundle.", file=sys.stderr)
    print(f"Bootstrap ID: {result.bootstrap_id}", file=sys.stderr)
    print(f"Expires at: {_format_expiry(result.expires_at_unix)}", file=sys.stderr)
    print(f"Scopes: {scopes}", file=sys.stderr)
    print(f"Installation pin: {result.pinned_installation_id}", file=sys.stderr)
    print("Secret: <redacted>; bundle written once to stdout.", file=sys.stderr)


def _format_expiry(expires_at_unix: float) -> str:
    return format_local(expires_at_unix, fmt="%Y-%m-%dT%H:%M:%S%z")


def _machine_row(machine: MachineRecord) -> dict[str, object]:
    return {
        "alias": machine.alias,
        "provider": machine.provider_ref,
        "endpoint": machine.endpoint,
        "credential_ref": machine.credential_ref,
        "installation_pin": machine.pinned_installation_id,
        "ssh_target": machine.effective_ssh_target,
        "ssh_target_configured": machine.ssh_target,
        "quarantined": machine.quarantined,
        "quarantine_reason": machine.quarantine_reason,
    }


def _candidate_row(candidate: DiscoveryCandidate) -> dict[str, object]:
    return {
        "key": candidate.key,
        "provider": candidate.provider_ref,
        "endpoint": candidate.endpoint,
        "display_name": candidate.display_name,
        "machine_selector": candidate.machine_selector,
        "installation_pin": candidate.installation_pin,
        "detail": candidate.detail,
    }


def _diagnostic_row(diagnostic: MachineDiagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity,
        "message": diagnostic.message,
        "alias": diagnostic.alias,
    }


def _status_row(
    status: MachineStatus,
    *,
    local: Mapping[str, str | int | None] | None = None,
) -> dict[str, object]:
    local = dict(local or {})
    return {
        "alias": status.alias,
        "state": status.state,
        "ok": status.ok,
        "provider": status.provider_ref,
        "endpoint": status.endpoint,
        "machine_selector": status.machine_selector,
        "installation_id": status.installation_id,
        "protocol_version": status.protocol_version,
        "capabilities": {
            key: list(value) for key, value in status.capabilities.items()
        },
        "gateway_version": _gateway_version_row(status.gateway_version),
        "service_versions": dict(status.service_versions),
        "capability_schema_version": status.capability_schema_version,
        "version_skew": _version_skew(status, local),
        "message": _status_message(status, local),
    }


def enrollment_result_row(result: EnrollmentResult) -> dict[str, object]:
    return {
        "alias": result.alias,
        "credential_ref": result.credential_ref,
        "machine_selector": result.machine_selector,
        "protocol_version": result.protocol_version,
        "installation_id": result.installation_id,
        "credential_id": result.credential_id,
        "capabilities": {
            key: list(value) for key, value in result.capabilities.items()
        },
        "quarantined": result.quarantined,
        "quarantine_reason": result.quarantine_reason,
    }


def _safe_error(exc: BaseException) -> str:
    return str(exc).replace("\n", " ")


def _status_message(
    status: MachineStatus,
    local: Mapping[str, str | int | None],
) -> str:
    details = _version_detail(status, local)
    if not details:
        return status.message
    return f"{status.message}; {details}"


def _version_detail(
    status: MachineStatus,
    local: Mapping[str, str | int | None],
) -> str:
    skew = _version_skew(status, local)
    if skew:
        return "version skew: " + "; ".join(skew) + "; restart target gateway"
    versions = _remote_version_summary(status)
    if versions:
        return f"versions: {versions}"
    return ""


def _remote_version_summary(status: MachineStatus) -> str:
    parts = [
        f"{label} {version}"
        for label, version in _remote_status_versions(status).items()
    ]
    if status.state == "ok" and status.gateway_version is None:
        parts.insert(0, "sase-gateway unknown")
    if status.capability_schema_version is not None:
        parts.append(f"fleet contract schema v{status.capability_schema_version}")
    return ", ".join(parts)


def _version_skew(
    status: MachineStatus,
    local: Mapping[str, str | int | None],
) -> list[str]:
    if status.state != "ok":
        return []
    skew: list[str] = []
    gateway = status.gateway_version
    if gateway is not None and gateway.service == "sase-gateway":
        local_version = _local_version(local, "sase-core", CORE_DISTRIBUTION_NAME)
        if isinstance(local_version, str) and gateway.package_version != local_version:
            skew.append(
                f"{gateway.service} remote {gateway.package_version} "
                f"!= local {CORE_DISTRIBUTION_NAME} {local_version}"
            )
    for label, remote in _unexpected_gateway_versions(status).items():
        local_version = local.get(label)
        if isinstance(local_version, str) and remote != local_version:
            skew.append(f"{label} remote {remote} != local {local_version}")
    local_schema = local.get("fleet_contract_schema")
    if (
        isinstance(local_schema, int)
        and status.capability_schema_version is not None
        and status.capability_schema_version != local_schema
    ):
        skew.append(
            "fleet contract "
            f"remote schema v{status.capability_schema_version} != local v{local_schema}"
        )
    return skew


def _remote_status_versions(status: MachineStatus) -> dict[str, str]:
    versions: dict[str, str] = {}
    if status.gateway_version is not None:
        versions[status.gateway_version.service] = (
            status.gateway_version.package_version
        )
    for label, version in _legacy_remote_status_versions(status).items():
        versions.setdefault(label, version)
    return versions


def _legacy_remote_status_versions(status: MachineStatus) -> dict[str, str]:
    remote = dict(status.service_versions)
    versions: dict[str, str] = {}
    host = _first_version(remote, "sase", HOST_DISTRIBUTION_NAME)
    core = _first_version(remote, "sase-core", CORE_DISTRIBUTION_NAME)
    if host:
        versions["sase"] = host
    if core:
        versions["sase-core"] = core
    return versions


def _unexpected_gateway_versions(status: MachineStatus) -> dict[str, str]:
    gateway = status.gateway_version
    if gateway is None or gateway.service == "sase-gateway":
        return {}
    return {gateway.service: gateway.package_version}


def _local_version(
    local: Mapping[str, str | int | None],
    *labels: str,
) -> str | int | None:
    for label in labels:
        version = local.get(label)
        if version is not None:
            return version
    return None


def _first_version(mapping: Mapping[str, str], *keys: str) -> str:
    for key in keys:
        version = mapping.get(key)
        if version:
            return version
    return ""


def _local_status_versions() -> dict[str, str | int | None]:
    versions: dict[str, str | int | None] = {}
    try:
        core_versions = collect_installed_core_versions()
    except Exception:  # noqa: BLE001 - status checks must never fail on metadata.
        core_versions = None
    if core_versions is not None:
        for package in core_versions.packages:
            versions[package.name] = package.installed_version
            versions[package.distribution_name] = package.installed_version
    versions["fleet_contract_schema"] = _local_fleet_contract_schema_version()
    return versions


def _local_fleet_contract_schema_version() -> int | None:
    try:
        from sase.core.rust import require_rust_binding

        version = require_rust_binding("fleet_contract_schema_version")()
    except Exception:  # noqa: BLE001 - status output should degrade gracefully.
        return None
    return int(version) if isinstance(version, int) else None


def _gateway_version_row(
    version: GatewayServiceVersion | None,
) -> dict[str, str] | None:
    return version.to_wire() if version is not None else None


__all__ = [
    "enrollment_result_row",
    "handle_machine_command",
    "machine_json_document",
    "read_enrollment_bundle",
]
