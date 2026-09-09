"""Optional remote-machine enrollment for ``sase init`` and ``sase machine init``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import getpass
from pathlib import Path
import sys
from typing import TextIO

from sase.dispatch.machine_init import (
    MachineInitApplyResult,
    MachineInitPlan,
    MachineInitService,
)
from sase.dispatch.models import EnrollmentResult
from sase.main.init_plan import InitAction, InitPlan


def plan_init_machine(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for optional remote-machine enrollment."""
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    check_mode = bool(getattr(args, "check", False))
    plan: MachineInitPlan = MachineInitService().plan(
        check_mode=check_mode, is_tty=stdin.isatty()
    )
    return InitPlan(
        command="machine",
        label="Machine",
        summary=plan.summary,
        actions=()
        if not plan.offer_enrollment
        else (
            InitAction(
                path=Path("remote machine enrollment"),
                operation="validate",
                detail="discover providers and optionally enroll selected machines",
            ),
        ),
        warnings=plan.warnings,
        requires_tty=plan.offer_enrollment,
    )


def run_init_machine(args: argparse.Namespace) -> int:
    """Discover, enroll, and activate remote machines, or print a check plan."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="machine",
                    label="Machine",
                    plan=plan_init_machine,
                    run=run_init_machine,
                ),
            ),
        )

    from .machine_handler import read_enrollment_bundle

    input_func: Callable[[str], str] = getattr(args, "_init_input_func", None) or input
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    getpass_func: Callable[[str], str] = (
        getattr(args, "_init_getpass_func", None) or getpass.getpass
    )
    if getattr(args, "_init_input_func", None) is None and not stdin.isatty():
        print(
            "error: remote machine enrollment requires an interactive TTY",
            file=sys.stderr,
        )
        return 1

    bundle_text: str | None = None
    if getattr(args, "bootstrap_file", None) or not stdin.isatty():
        bundle_text = read_enrollment_bundle(
            args,
            stdin=stdin,
            getpass_func=getpass_func,
        )

    service = MachineInitService(
        machine_service=getattr(args, "_init_machine_service", None),
        apply_chezmoi_fn=getattr(args, "_init_apply_chezmoi_fn", None),
        use_chezmoi_fn=getattr(args, "_init_use_chezmoi_fn", None),
        registry_target_fn=getattr(args, "_init_registry_target_fn", None),
    )
    result = service.apply(
        input_func=input_func,
        getpass_func=getpass_func,
        stdin=stdin,
        bundle_text=bundle_text,
        timeout_seconds=getattr(args, "timeout", None),
        provider_refs=tuple(getattr(args, "provider", None) or ()),
    )
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        from .machine_handler import machine_json_document

        print(machine_json_document(_apply_json_payload(result)))
    else:
        _print_apply_result(result)
    return result.exit_code


def handle_init_machine_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init machine``."""
    sys.exit(run_init_machine(args))


def _apply_json_payload(result: MachineInitApplyResult) -> dict[str, object]:
    from .machine_handler import enrollment_result_row

    return {
        "subcommand": "init",
        "ok": result.exit_code == 0,
        "results": [enrollment_result_row(item) for item in result.enrollments],
        "skipped": [_reconciled_row(item) for item in result.skipped],
        "repair": [_reconciled_row(item) for item in result.repair],
        "recovery": list(result.recovery_messages),
        "errors": list(result.errors),
        "diagnostics": [_diagnostic_row(item) for item in result.diagnostics],
        "cancelled": result.cancelled,
        "nothing_to_enroll": result.nothing_to_enroll,
        "chezmoi_proc_id": result.chezmoi_proc_id or None,
        "chezmoi_in_progress": result.chezmoi_in_progress,
    }


def _diagnostic_row(item: object) -> dict[str, object]:
    from sase.dispatch.models import MachineDiagnostic

    assert isinstance(item, MachineDiagnostic)
    return {
        "code": item.code,
        "severity": item.severity,
        "message": item.message,
        "alias": item.alias,
    }


def _reconciled_row(item: object) -> dict[str, object]:
    from sase.dispatch.machine_init import ReconciledCandidate

    assert isinstance(item, ReconciledCandidate)
    candidate = item.candidate
    return {
        "alias": item.alias,
        "status": item.status,
        "reason": item.reason,
        "provider": candidate.provider_ref,
        "endpoint": candidate.endpoint,
        "display_name": candidate.display_name,
        "installation_pin": candidate.installation_pin,
    }


def _print_apply_result(result: MachineInitApplyResult) -> None:
    for message in result.errors:
        print(f"error: {message}", file=sys.stderr)
    for message in result.recovery_messages:
        print(message, file=sys.stderr)
    for item in result.repair:
        print(
            f"{item.alias}: {item.reason}. The existing pin was not overwritten.",
            file=sys.stderr,
        )
    if result.cancelled or result.nothing_to_enroll:
        return
    for enrollment in result.enrollments:
        if result.exit_code != 0 and not enrollment.quarantined:
            continue
        print(_enrollment_line(enrollment))


def _enrollment_line(result: EnrollmentResult) -> str:
    if result.quarantined:
        reason = result.quarantine_reason or "quarantined"
        return f"{result.alias}: quarantined as {result.machine_selector or 'remote machine'} ({reason})"
    return f"{result.alias}: enrolled as {result.machine_selector or 'remote machine'}"


__all__ = ["handle_init_machine_command", "plan_init_machine", "run_init_machine"]
