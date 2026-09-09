"""Planner and apply service for canonical remote-machine initialization.

Planning inspects only the local merged dispatch config and never invokes
providers. Apply discovers only when explicitly invoked, reconciles candidate
identities against enrolled pins, and activates a written record before the
caller may report enrollment success.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import sys
from typing import TextIO

from sase.config import core as config_core
from sase.config.targets import resolve_write_path
from sase.dispatch._machine_init_activation import (
    ActivationOutcome,
    ChezmoiApplyOutcome,
    run_scoped_chezmoi_apply,
)
from sase.dispatch._machine_init_interaction import (
    apply_recovery_message,
    discovery_failed,
    hello_recovery_message,
    non_info_messages,
    print_diagnostics,
    print_enrolled,
    print_reconciled,
    read_alias,
    read_bundle_once,
    select_candidates,
    status_detail,
)
from sase.dispatch._machine_init_reconcile import reconcile_candidates
from sase.dispatch._machine_init_types import (
    ApplyChezmoiFn,
    GetPassFunc,
    InputFunc,
    MachineInitApplyResult,
    MachineInitPlan,
    ReconciledCandidate,
)
from sase.dispatch.config import load_dispatch_config, machine_registry_target_path
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    DispatchConfig,
    DispatchError,
    DiscoveryCandidate,
    EnrollmentResult,
    MachineRecord,
)


class MachineInitService:
    """Dispatch-owned planner/apply workflow for ``sase machine init``."""

    def __init__(
        self,
        *,
        machine_service: MachineService | None = None,
        load_config_fn: Callable[[], DispatchConfig] | None = None,
        apply_chezmoi_fn: ApplyChezmoiFn | None = None,
        use_chezmoi_fn: Callable[[], bool] | None = None,
        registry_target_fn: Callable[[], Path] | None = None,
        clear_config_cache_fn: Callable[[], None] | None = None,
    ) -> None:
        self.machine_service = machine_service or MachineService()
        self.load_config_fn = load_config_fn or load_dispatch_config
        self.apply_chezmoi_fn = apply_chezmoi_fn
        self.use_chezmoi_fn = use_chezmoi_fn or config_core.get_use_chezmoi
        self.registry_target_fn = registry_target_fn or machine_registry_target_path
        self.clear_config_cache_fn = (
            clear_config_cache_fn or config_core.clear_config_cache
        )

    def plan(self, *, check_mode: bool, is_tty: bool) -> MachineInitPlan:
        """Return a pure offline plan from local merged configuration."""
        config = self.load_config_fn()
        warnings = non_info_messages(config)
        enrolled = config.machines
        if enrolled:
            aliases = ", ".join(machine.alias for machine in enrolled)
            summary = f"remote machines are configured: {aliases}"
        elif config.discovery_enabled_provider_refs:
            summary = "remote machine enrollment is optional"
        else:
            summary = "no remote machine discovery providers are configured"

        offer = (
            not check_mode and is_tty and bool(config.discovery_enabled_provider_refs)
        )
        if not offer:
            return MachineInitPlan(
                summary=summary,
                offer_enrollment=False,
                warnings=warnings,
                enrolled=enrolled,
            )
        return MachineInitPlan(
            summary="remote machine enrollment can discover configured providers",
            offer_enrollment=True,
            warnings=warnings,
            enrolled=enrolled,
        )

    def reconcile(
        self,
        candidates: Sequence[DiscoveryCandidate],
        enrolled: Sequence[MachineRecord] | None = None,
    ) -> tuple[ReconciledCandidate, ...]:
        """Classify candidates without mutating pins or invoking providers."""
        records = (
            tuple(enrolled) if enrolled is not None else self.load_config_fn().machines
        )
        return reconcile_candidates(candidates, records)

    def apply(
        self,
        *,
        input_func: InputFunc,
        getpass_func: GetPassFunc,
        stdin: TextIO,
        bundle_text: str | None = None,
        timeout_seconds: float | None = None,
        provider_refs: Sequence[str] = (),
    ) -> MachineInitApplyResult:
        """Discover, reconcile, enroll selected machines, and activate them."""
        try:
            discovery = self.machine_service.discover_detailed(
                provider_refs=provider_refs,
                timeout_seconds=timeout_seconds,
            )
        except DispatchError as exc:
            return MachineInitApplyResult(exit_code=1, errors=(str(exc),))

        candidates = discovery.candidates
        diagnostics = discovery.diagnostics
        enrolled = self.load_config_fn().machines
        reconciled = self.reconcile(candidates, enrolled)
        skipped = tuple(item for item in reconciled if item.status == "enrolled")
        repair = tuple(item for item in reconciled if item.status == "repair")
        new_items = tuple(item for item in reconciled if item.status == "new")
        new_candidates = tuple(item.candidate for item in new_items)

        print_enrolled(enrolled)
        print_reconciled(reconciled)
        print_diagnostics(diagnostics)
        if not new_candidates:
            if not candidates:
                print("No remote machine candidates found.", file=sys.stderr)
            else:
                print("No new remote machines to enroll.", file=sys.stderr)
            if discovery_failed(diagnostics):
                return MachineInitApplyResult(
                    exit_code=1,
                    skipped=skipped,
                    repair=repair,
                    diagnostics=diagnostics,
                    errors=tuple(
                        item.message for item in diagnostics if item.severity == "error"
                    ),
                )
            return MachineInitApplyResult(
                exit_code=0,
                skipped=skipped,
                repair=repair,
                diagnostics=diagnostics,
                nothing_to_enroll=True,
            )

        try:
            selected = select_candidates(input_func, new_candidates)
        except (EOFError, KeyboardInterrupt):
            print("\nremote machine enrollment cancelled.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=1,
                skipped=skipped,
                repair=repair,
                diagnostics=diagnostics,
                cancelled=True,
            )
        except ValueError as exc:
            return MachineInitApplyResult(
                exit_code=1,
                skipped=skipped,
                repair=repair,
                diagnostics=diagnostics,
                errors=(str(exc),),
            )
        if not selected:
            print("No remote machines enrolled.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=0,
                skipped=skipped,
                repair=repair,
                diagnostics=diagnostics,
                nothing_to_enroll=True,
            )

        enrollments: list[EnrollmentResult] = []
        recovery: list[str] = []
        for candidate in selected:
            try:
                alias = read_alias(input_func, candidate)
                bundle = (
                    bundle_text
                    if bundle_text is not None
                    else read_bundle_once(getpass_func, stdin)
                )
                result = self.machine_service.add_machine(
                    alias=alias,
                    endpoint=candidate.endpoint,
                    provider_ref=candidate.provider_ref,
                    bundle_text=bundle,
                    timeout_seconds=timeout_seconds,
                )
            except (EOFError, KeyboardInterrupt):
                print("\nremote machine enrollment cancelled.", file=sys.stderr)
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    diagnostics=diagnostics,
                    cancelled=True,
                )
            except Exception as exc:  # noqa: BLE001 - interactive command boundary.
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                    diagnostics=diagnostics,
                    errors=(f"failed to enroll {candidate.endpoint}: {exc}",),
                )

            activation = self.activate(
                alias=alias,
                expected=result,
                timeout_seconds=timeout_seconds,
            )
            if activation.recovery_message:
                recovery.append(activation.recovery_message)
            enrollments.append(result)
            if result.quarantined:
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                    diagnostics=diagnostics,
                    chezmoi_proc_id=activation.proc_id,
                    chezmoi_in_progress=activation.in_progress,
                )
            if not activation.ok:
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                    diagnostics=diagnostics,
                    errors=activation.errors,
                    chezmoi_proc_id=activation.proc_id,
                    chezmoi_in_progress=activation.in_progress,
                )
        return MachineInitApplyResult(
            exit_code=0,
            enrollments=tuple(enrollments),
            skipped=skipped,
            repair=repair,
            recovery_messages=tuple(recovery),
            diagnostics=diagnostics,
        )

    def activate(
        self,
        *,
        alias: str,
        expected: EnrollmentResult,
        timeout_seconds: float | None = None,
    ) -> ActivationOutcome:
        """Deploy, reload, and verify an enrollment before success is claimed."""
        apply_outcome = self._apply_overlay_if_needed()
        self.clear_config_cache_fn()
        config = self.load_config_fn()
        record = config.machine_by_alias().get(alias)
        expected_record = expected.record
        if apply_outcome.failed:
            errors = tuple(
                message
                for message in (
                    apply_outcome.error,
                    (
                        f"tracked chezmoi apply proc {apply_outcome.proc_id} "
                        "is still in progress"
                        if apply_outcome.in_progress and apply_outcome.proc_id
                        else ""
                    ),
                )
                if message
            )
            return ActivationOutcome(
                ok=False,
                errors=errors,
                recovery_message=apply_recovery_message(alias),
                proc_id=apply_outcome.proc_id,
                in_progress=apply_outcome.in_progress,
            )
        if expected_record is None:
            return ActivationOutcome(
                ok=False,
                errors=(f"{alias}: enrollment did not produce a machine record",),
                recovery_message=hello_recovery_message(alias, "missing record"),
            )
        if record is None:
            return ActivationOutcome(
                ok=False,
                errors=(
                    f"{alias}: applied configuration is missing the machine record",
                ),
                recovery_message=apply_recovery_message(alias),
            )
        if (
            record.endpoint != expected_record.endpoint
            or record.provider_ref != expected_record.provider_ref
            or record.pinned_installation_id != expected_record.pinned_installation_id
        ):
            return ActivationOutcome(
                ok=False,
                errors=(
                    f"{alias}: applied machine record does not match the enrollment",
                ),
                recovery_message=apply_recovery_message(alias),
            )
        if expected.quarantined:
            return ActivationOutcome(ok=True)
        credential = self.machine_service.credential_store.get(record.credential_ref)
        if credential is None:
            return ActivationOutcome(
                ok=False,
                errors=(f"{alias}: local credential ref is missing",),
                recovery_message=hello_recovery_message(
                    alias, "local credential ref is missing"
                ),
            )

        statuses = self.machine_service.status(
            (alias,),
            timeout_seconds=timeout_seconds,
        )
        status = statuses[0] if statuses else None
        if status is None or not status.ok:
            detail = status_detail(status)
            return ActivationOutcome(
                ok=False,
                errors=(f"{alias}: authenticated hello failed: {detail}",),
                recovery_message=hello_recovery_message(alias, detail),
            )
        return ActivationOutcome(ok=True)

    def _apply_overlay_if_needed(self) -> ChezmoiApplyOutcome:
        if not self.use_chezmoi_fn():
            return ChezmoiApplyOutcome()
        target = self.registry_target_fn()
        write_path = resolve_write_path(str(target), use_chezmoi=True)
        if write_path is None or write_path == target:
            return ChezmoiApplyOutcome()
        try:
            return run_scoped_chezmoi_apply(target, apply_fn=self.apply_chezmoi_fn)
        except FileNotFoundError:
            return ChezmoiApplyOutcome(error="chezmoi not found on PATH")
        except OSError as exc:
            return ChezmoiApplyOutcome(error=f"chezmoi apply failed: {exc}")


__all__ = [
    "MachineInitApplyResult",
    "MachineInitPlan",
    "MachineInitService",
    "ReconciledCandidate",
]
