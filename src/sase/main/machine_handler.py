"""Handler for ``sase machine`` commands."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys
from typing import Any

from sase.dispatch.config import load_dispatch_config, remote_dispatch_enabled
from sase.dispatch.fleet_client import FleetGatewayError
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    DispatchError,
    DiscoveryCandidate,
    EnrollmentResult,
    MachineRecord,
    MachineStatus,
)


def handle_machine_command(args: argparse.Namespace) -> int:
    service = MachineService()
    subcommand = getattr(args, "machine_subcommand", "list")
    try:
        if subcommand == "add":
            return _handle_add(args, service)
        if subcommand == "discover":
            return _handle_discover(args, service)
        if subcommand == "list":
            return _handle_list(args)
        if subcommand == "remove":
            return _handle_remove(args, service)
        if subcommand == "rename":
            return _handle_rename(args, service)
        if subcommand == "repair":
            return _handle_repair(args, service)
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


def _handle_add(args: argparse.Namespace, service: MachineService) -> int:
    provider_ref, endpoint = _resolve_provider_endpoint(args)
    if not endpoint:
        raise DispatchError("an HTTPS endpoint or candidate key is required")
    result = service.add_machine(
        alias=args.alias,
        endpoint=endpoint,
        provider_ref=provider_ref,
        bundle_text=_read_bundle(args),
        timeout_seconds=getattr(args, "timeout", None),
    )
    if getattr(args, "json", False):
        print(_json({"result": _enrollment_row(result)}))
    else:
        state = "quarantined" if result.quarantined else "enrolled"
        print(f"{args.alias}: {state} as {result.machine_selector or 'remote machine'}")
    return 0 if not result.quarantined else 1


def _handle_discover(args: argparse.Namespace, service: MachineService) -> int:
    candidates = service.discover(
        provider_refs=tuple(getattr(args, "provider", None) or ()),
        timeout_seconds=getattr(args, "timeout", None),
    )
    if getattr(args, "json", False):
        print(_json({"candidates": [_candidate_row(item) for item in candidates]}))
    elif not candidates:
        print("No remote machine candidates found.")
    else:
        for candidate in candidates:
            label = candidate.display_name or candidate.endpoint
            print(f"{candidate.key}\t{label}")
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    config = load_dispatch_config()
    if getattr(args, "json", False):
        print(
            _json(
                {
                    "remote_dispatch_enabled": remote_dispatch_enabled(),
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
                f"{machine.alias}\t{state}\t{machine.provider_ref}\t{machine.endpoint}"
            )
    return 1 if any(item.severity == "error" for item in config.diagnostics) else 0


def _handle_remove(args: argparse.Namespace, service: MachineService) -> int:
    if not getattr(args, "yes", False) and sys.stdin.isatty():
        answer = input(f"Remove remote machine alias '{args.alias}'? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("Cancelled.")
            return 1
    record = service.remove_machine(args.alias)
    if getattr(args, "json", False):
        print(_json({"removed": _machine_row(record)}))
    else:
        print(f"Removed remote machine alias {record.alias}.")
    return 0


def _handle_rename(args: argparse.Namespace, service: MachineService) -> int:
    record = service.rename_machine(args.old_alias, args.new_alias)
    if getattr(args, "json", False):
        print(_json({"renamed": _machine_row(record)}))
    else:
        print(f"Renamed remote machine alias {args.old_alias} to {record.alias}.")
    return 0


def _handle_repair(args: argparse.Namespace, service: MachineService) -> int:
    result = service.repair_machine(
        alias=args.alias,
        bundle_text=_read_bundle(args),
        timeout_seconds=getattr(args, "timeout", None),
    )
    if getattr(args, "json", False):
        print(_json({"result": _enrollment_row(result)}))
    else:
        state = "quarantined" if result.quarantined else "repaired"
        print(f"{args.alias}: {state}")
    return 0 if not result.quarantined else 1


def _handle_status(args: argparse.Namespace, service: MachineService) -> int:
    statuses = service.status(
        tuple(getattr(args, "aliases", ()) or ()),
        timeout_seconds=getattr(args, "timeout", None),
    )
    if getattr(args, "json", False):
        print(_json({"statuses": [_status_row(status) for status in statuses]}))
    else:
        for status in statuses:
            print(f"{status.alias}\t{status.state}\t{status.message}")
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


def _read_bundle(args: argparse.Namespace) -> str:
    path = getattr(args, "bootstrap_file", None)
    if path:
        return Path(path).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        raise DispatchError(
            "enrollment bundle requires --bootstrap-file or an interactive TTY"
        )
    return getpass.getpass("Paste enrollment bundle: ")


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "command": "machine",
            **payload,
        },
        indent=2,
        sort_keys=True,
    )


def _machine_row(machine: MachineRecord) -> dict[str, object]:
    return {
        "alias": machine.alias,
        "provider": machine.provider_ref,
        "endpoint": machine.endpoint,
        "credential_ref": machine.credential_ref,
        "installation_pin": machine.pinned_installation_id,
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


def _status_row(status: MachineStatus) -> dict[str, object]:
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
        "message": status.message,
    }


def _enrollment_row(result: EnrollmentResult) -> dict[str, object]:
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


__all__ = ["handle_machine_command"]
