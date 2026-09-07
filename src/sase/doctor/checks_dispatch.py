"""Dispatch machine doctor checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.dispatch.config import (
    load_dispatch_config,
    remote_dispatch_enabled,
    validate_connection_plan,
)
from sase.dispatch.credentials import CredentialStoreError, LocalCredentialStore
from sase.dispatch.machine_service import MachineService
from sase.dispatch.providers import collect_dispatch_providers

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def dispatch_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return dispatch-specific doctor specs."""
    return (
        CheckSpec(
            id="dispatch.config",
            group="dispatch",
            title="Dispatch machine config",
            runner=lambda: _check_dispatch_config(context),
        ),
        CheckSpec(
            id="dispatch.credentials",
            group="dispatch",
            title="Dispatch credentials",
            runner=lambda: _check_dispatch_credentials(context),
        ),
        CheckSpec(
            id="dispatch.live",
            group="dispatch",
            title="Dispatch gateway hello",
            runner=lambda: _check_dispatch_live(context),
            deep=True,
        ),
    )


def _check_dispatch_config(context: DoctorContext) -> DiagnosticCheck:
    del context
    config = load_dispatch_config()
    inventory = collect_dispatch_providers()
    providers = inventory.by_ref()
    details: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    for diagnostic in (*config.diagnostics, *inventory.diagnostics):
        target = errors if diagnostic.severity == "error" else warnings
        target.append(diagnostic.message)

    for machine in config.machines:
        if machine.provider_ref not in providers:
            errors.append(
                f"{machine.alias}: provider {machine.provider_ref} is not installed"
            )
        elif not config.provider_enabled(machine.provider_ref):
            errors.append(
                f"{machine.alias}: provider {machine.provider_ref} is disabled"
            )
        for diagnostic in validate_connection_plan(machine):
            if diagnostic.severity == "error":
                errors.append(diagnostic.message)
            else:
                warnings.append(diagnostic.message)

    if errors:
        return _check(
            "dispatch.config",
            "Dispatch machine config",
            "ERROR",
            f"{len(errors)} dispatch config error(s)",
            details=tuple(errors[:10]),
            data={
                "machine_count": len(config.machines),
                "provider_count": len(providers),
                "remote_dispatch_enabled": remote_dispatch_enabled(),
            },
            next_steps=(
                "Repair dispatch.machines entries or rerun `sase machine repair ALIAS`.",
            ),
        )
    if warnings:
        return _check(
            "dispatch.config",
            "Dispatch machine config",
            "WARN",
            f"{len(warnings)} dispatch config warning(s)",
            details=tuple(warnings[:10]),
            data={
                "machine_count": len(config.machines),
                "provider_count": len(providers),
                "remote_dispatch_enabled": remote_dispatch_enabled(),
            },
        )
    return _check(
        "dispatch.config",
        "Dispatch machine config",
        "OK",
        "dispatch machine config is valid",
        details=tuple(details),
        data={
            "machine_count": len(config.machines),
            "provider_count": len(providers),
            "remote_dispatch_enabled": remote_dispatch_enabled(),
        },
    )


def _check_dispatch_credentials(context: DoctorContext) -> DiagnosticCheck:
    del context
    config = load_dispatch_config()
    store = LocalCredentialStore()
    errors: list[str] = []
    warnings: list[str] = []
    expected = {machine.credential_ref: machine for machine in config.machines}
    try:
        metadata = store.metadata()
    except CredentialStoreError as exc:
        return _check(
            "dispatch.credentials",
            "Dispatch credentials",
            "ERROR",
            "dispatch credential store is unreadable",
            details=(str(exc),),
        )
    actual = {str(item["ref"]): item for item in metadata if "ref" in item}
    for ref, machine in sorted(expected.items()):
        row = actual.get(ref)
        if row is None:
            errors.append(f"{machine.alias}: credential ref {ref} is missing")
            continue
        if row.get("installation_id") != machine.pinned_installation_id:
            errors.append(
                f"{machine.alias}: credential installation does not match pin"
            )
        if row.get("provider_ref") != machine.provider_ref:
            errors.append(f"{machine.alias}: credential provider does not match config")
        if row.get("endpoint") != machine.endpoint:
            errors.append(f"{machine.alias}: credential endpoint does not match config")
    for ref in sorted(set(actual) - set(expected)):
        warnings.append(f"orphan dispatch credential ref: {ref}")

    if errors:
        return _check(
            "dispatch.credentials",
            "Dispatch credentials",
            "ERROR",
            f"{len(errors)} dispatch credential error(s)",
            details=tuple(errors[:10]),
            data={"expected_refs": len(expected), "stored_refs": len(actual)},
            next_steps=("Rerun `sase machine repair ALIAS` for mismatched aliases.",),
        )
    if warnings:
        return _check(
            "dispatch.credentials",
            "Dispatch credentials",
            "WARN",
            f"{len(warnings)} dispatch credential warning(s)",
            details=tuple(warnings[:10]),
            data={"expected_refs": len(expected), "stored_refs": len(actual)},
        )
    return _check(
        "dispatch.credentials",
        "Dispatch credentials",
        "OK",
        "dispatch credentials match configured machine aliases",
        data={"expected_refs": len(expected), "stored_refs": len(actual)},
    )


def _check_dispatch_live(context: DoctorContext) -> DiagnosticCheck:
    del context
    if not remote_dispatch_enabled():
        return _check(
            "dispatch.live",
            "Dispatch gateway hello",
            "SKIP",
            "remote_dispatch is disabled",
        )
    config = load_dispatch_config()
    if not config.machines:
        return _check(
            "dispatch.live",
            "Dispatch gateway hello",
            "SKIP",
            "no remote machines are configured",
        )
    statuses = MachineService().status()
    failures = [status for status in statuses if not status.ok]
    if failures:
        return _check(
            "dispatch.live",
            "Dispatch gateway hello",
            "ERROR",
            f"{len(failures)} dispatch gateway hello check(s) failed",
            details=tuple(
                f"{status.alias}: {status.message}" for status in failures[:10]
            ),
            data={"checked": len(statuses), "failed": len(failures)},
        )
    return _check(
        "dispatch.live",
        "Dispatch gateway hello",
        "OK",
        "all configured dispatch gateways answered hello",
        data={"checked": len(statuses), "failed": 0},
    )


def _check(
    check_id: str,
    title: str,
    status: str,
    summary: str,
    *,
    details: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    data: dict[str, object] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        group="dispatch",
        status=status,  # type: ignore[arg-type]
        title=title,
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


__all__ = [
    "dispatch_check_specs",
]
