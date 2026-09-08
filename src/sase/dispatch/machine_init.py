"""Planner and apply service for canonical remote-machine initialization.

Planning inspects only the local merged dispatch config and never invokes
providers. Apply discovers only when explicitly invoked, reconciles candidate
identities against enrolled pins, and activates a written record before the
caller may report enrollment success.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Literal, TextIO

from sase.config import core as config_core
from sase.config.targets import resolve_write_path
from sase.dispatch.config import load_dispatch_config, machine_registry_target_path
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import (
    DispatchConfig,
    DispatchError,
    DiscoveryCandidate,
    EnrollmentResult,
    MachineRecord,
    MachineStatus,
    validate_machine_alias,
)

InputFunc = Callable[[str], str]
GetPassFunc = Callable[[str], str]
ApplyChezmoiFn = Callable[[Path | str], subprocess.CompletedProcess[str]]
CandidateDisposition = Literal["new", "enrolled", "repair"]


@dataclass(frozen=True)
class MachineInitPlan:
    """Offline machine-initialization plan (no provider or network IO)."""

    summary: str
    offer_enrollment: bool
    warnings: tuple[str, ...] = ()
    enrolled: tuple[MachineRecord, ...] = ()


@dataclass(frozen=True)
class ReconciledCandidate:
    """One discovery candidate classified against the local registry."""

    candidate: DiscoveryCandidate
    status: CandidateDisposition
    alias: str = ""
    reason: str = ""


@dataclass(frozen=True)
class MachineInitApplyResult:
    """Outcome of an explicit machine-init apply."""

    exit_code: int
    enrollments: tuple[EnrollmentResult, ...] = ()
    skipped: tuple[ReconciledCandidate, ...] = ()
    repair: tuple[ReconciledCandidate, ...] = ()
    recovery_messages: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    cancelled: bool = False
    nothing_to_enroll: bool = False


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
        warnings = _non_info_messages(config)
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
        by_pin = {
            record.pinned_installation_id: record
            for record in records
            if record.pinned_installation_id
        }
        by_endpoint = {
            (record.provider_ref, record.endpoint): record for record in records
        }
        reconciled: list[ReconciledCandidate] = []
        for candidate in candidates:
            pin_match = (
                by_pin.get(candidate.installation_pin)
                if candidate.installation_pin
                else None
            )
            endpoint_match = by_endpoint.get(
                (candidate.provider_ref, candidate.endpoint)
            )
            if pin_match is not None:
                reconciled.append(
                    ReconciledCandidate(
                        candidate=candidate,
                        status="enrolled",
                        alias=pin_match.alias,
                        reason="already enrolled",
                    )
                )
            elif (
                endpoint_match is not None
                and candidate.installation_pin
                and candidate.installation_pin != endpoint_match.pinned_installation_id
            ):
                reconciled.append(
                    ReconciledCandidate(
                        candidate=candidate,
                        status="repair",
                        alias=endpoint_match.alias,
                        reason=(
                            "installation identity changed; run "
                            f"`sase machine repair {endpoint_match.alias}`"
                        ),
                    )
                )
            elif endpoint_match is not None:
                reconciled.append(
                    ReconciledCandidate(
                        candidate=candidate,
                        status="enrolled",
                        alias=endpoint_match.alias,
                        reason="already enrolled",
                    )
                )
            else:
                reconciled.append(
                    ReconciledCandidate(candidate=candidate, status="new")
                )
        return tuple(reconciled)

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
            candidates = self.machine_service.discover(
                provider_refs=provider_refs,
                timeout_seconds=timeout_seconds,
            )
        except DispatchError as exc:
            return MachineInitApplyResult(exit_code=1, errors=(str(exc),))

        enrolled = self.load_config_fn().machines
        reconciled = self.reconcile(candidates, enrolled)
        skipped = tuple(item for item in reconciled if item.status == "enrolled")
        repair = tuple(item for item in reconciled if item.status == "repair")
        new_items = tuple(item for item in reconciled if item.status == "new")
        new_candidates = tuple(item.candidate for item in new_items)

        _print_enrolled(enrolled)
        _print_reconciled(reconciled)
        if not candidates and not enrolled:
            print("No remote machine candidates found.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=0,
                skipped=skipped,
                repair=repair,
                nothing_to_enroll=True,
            )
        if not new_candidates:
            if not candidates:
                print("No remote machine candidates found.", file=sys.stderr)
            else:
                print("No new remote machines to enroll.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=0,
                skipped=skipped,
                repair=repair,
                nothing_to_enroll=True,
            )

        try:
            selected = _select_candidates(input_func, new_candidates)
        except (EOFError, KeyboardInterrupt):
            print("\nremote machine enrollment cancelled.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=1,
                skipped=skipped,
                repair=repair,
                cancelled=True,
            )
        except ValueError as exc:
            return MachineInitApplyResult(
                exit_code=1,
                skipped=skipped,
                repair=repair,
                errors=(str(exc),),
            )
        if not selected:
            print("No remote machines enrolled.", file=sys.stderr)
            return MachineInitApplyResult(
                exit_code=0,
                skipped=skipped,
                repair=repair,
                nothing_to_enroll=True,
            )

        enrollments: list[EnrollmentResult] = []
        recovery: list[str] = []
        for candidate in selected:
            try:
                alias = _read_alias(input_func, candidate)
                bundle = (
                    bundle_text
                    if bundle_text is not None
                    else _read_bundle_once(getpass_func, stdin)
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
                    cancelled=True,
                )
            except Exception as exc:  # noqa: BLE001 - interactive command boundary.
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                    errors=(f"failed to enroll {candidate.endpoint}: {exc}",),
                )

            activation = self.activate(
                alias=alias,
                expected=result,
                timeout_seconds=timeout_seconds,
            )
            if activation.recovery_message:
                recovery.append(activation.recovery_message)
            if result.quarantined:
                enrollments.append(result)
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                )
            if not activation.ok:
                enrollments.append(result)
                return MachineInitApplyResult(
                    exit_code=1,
                    enrollments=tuple(enrollments),
                    skipped=skipped,
                    repair=repair,
                    recovery_messages=tuple(recovery),
                    errors=activation.errors,
                )
            enrollments.append(result)
        return MachineInitApplyResult(
            exit_code=0,
            enrollments=tuple(enrollments),
            skipped=skipped,
            repair=repair,
            recovery_messages=tuple(recovery),
        )

    def activate(
        self,
        *,
        alias: str,
        expected: EnrollmentResult,
        timeout_seconds: float | None = None,
    ) -> _ActivationOutcome:
        """Deploy, reload, and verify an enrollment before success is claimed."""
        apply_failed, apply_error = self._apply_overlay_if_needed()
        self.clear_config_cache_fn()
        config = self.load_config_fn()
        record = config.machine_by_alias().get(alias)
        expected_record = expected.record
        if apply_failed:
            return _ActivationOutcome(
                ok=False,
                errors=(apply_error,) if apply_error else (),
                recovery_message=_apply_recovery_message(alias),
            )
        if expected_record is None:
            return _ActivationOutcome(
                ok=False,
                errors=(f"{alias}: enrollment did not produce a machine record",),
                recovery_message=_hello_recovery_message(alias, "missing record"),
            )
        if record is None:
            return _ActivationOutcome(
                ok=False,
                errors=(
                    f"{alias}: applied configuration is missing the machine record",
                ),
                recovery_message=_apply_recovery_message(alias),
            )
        if (
            record.endpoint != expected_record.endpoint
            or record.provider_ref != expected_record.provider_ref
            or record.pinned_installation_id != expected_record.pinned_installation_id
        ):
            return _ActivationOutcome(
                ok=False,
                errors=(
                    f"{alias}: applied machine record does not match the enrollment",
                ),
                recovery_message=_apply_recovery_message(alias),
            )
        if expected.quarantined:
            return _ActivationOutcome(ok=True)
        credential = self.machine_service.credential_store.get(record.credential_ref)
        if credential is None:
            return _ActivationOutcome(
                ok=False,
                errors=(f"{alias}: local credential ref is missing",),
                recovery_message=_hello_recovery_message(
                    alias, "local credential ref is missing"
                ),
            )

        statuses = self.machine_service.status(
            (alias,),
            timeout_seconds=timeout_seconds,
        )
        status = statuses[0] if statuses else None
        if status is None or not status.ok:
            detail = _status_detail(status)
            return _ActivationOutcome(
                ok=False,
                errors=(f"{alias}: authenticated hello failed: {detail}",),
                recovery_message=_hello_recovery_message(alias, detail),
            )
        return _ActivationOutcome(ok=True)

    def _apply_overlay_if_needed(self) -> tuple[bool, str]:
        if not self.use_chezmoi_fn():
            return False, ""
        target = self.registry_target_fn()
        write_path = resolve_write_path(str(target), use_chezmoi=True)
        if write_path is None or write_path == target:
            return False, ""
        try:
            result = _run_scoped_chezmoi_apply(target, apply_fn=self.apply_chezmoi_fn)
        except FileNotFoundError:
            return True, "chezmoi not found on PATH"
        except OSError as exc:
            return True, f"chezmoi apply failed: {exc}"
        if result.returncode != 0:
            detail = (
                result.stderr or result.stdout or f"exit {result.returncode}"
            ).strip()
            return True, f"chezmoi apply failed: {detail}"
        return False, ""


@dataclass(frozen=True)
class _ActivationOutcome:
    ok: bool
    errors: tuple[str, ...] = ()
    recovery_message: str = ""


def _run_scoped_chezmoi_apply(
    target: Path | str,
    *,
    apply_fn: ApplyChezmoiFn | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the scoped ``apply_chezmoi`` operation from a durable tracked proc.

    The argv matches :func:`sase.config.targets.apply_chezmoi` so the supervisor
    performs the same scoped, forced apply. Callers inject ``apply_fn`` in tests.
    A non-zero exit is returned, not raised.
    """
    if apply_fn is not None:
        return apply_fn(target)
    from sase.procs import submit_proc, wait_for_proc

    expanded = str(Path(target).expanduser())
    argv = ["chezmoi", "apply", "--force", expanded]
    try:
        proc = submit_proc(
            argv,
            label=f"chezmoi apply {expanded}",
            cwd=Path.home(),
            origin="machine-init",
            tags=("machine-init", "chezmoi-apply"),
            timeout_seconds=900,
        )
        finished = wait_for_proc(proc.proc_id, timeout=900)
    except Exception:  # noqa: BLE001 - fall back to the in-process apply helper.
        from sase.config.targets import apply_chezmoi

        return apply_chezmoi(target)
    returncode = 0 if finished.status == "success" else (finished.exit_code or 1)
    log_text = ""
    if finished.log_path:
        try:
            log_text = Path(finished.log_path).read_text(encoding="utf-8")
        except OSError:
            log_text = ""
    return subprocess.CompletedProcess(
        argv,
        returncode,
        stdout=log_text,
        stderr=finished.message or "",
    )


def _non_info_messages(config: DispatchConfig) -> tuple[str, ...]:
    return tuple(item.message for item in config.diagnostics if item.severity != "info")


def _print_enrolled(enrolled: Sequence[MachineRecord]) -> None:
    if not enrolled:
        return
    print("Configured remote machines:", file=sys.stderr)
    for machine in enrolled:
        state = "quarantined" if machine.quarantined else "enrolled"
        print(
            f"  {machine.alias}\t{state}\t{machine.provider_ref}\t{machine.endpoint}",
            file=sys.stderr,
        )


def _print_reconciled(items: Sequence[ReconciledCandidate]) -> None:
    if not items:
        return
    print("Remote machine candidates:", file=sys.stderr)
    new_index = 0
    for item in items:
        candidate = item.candidate
        label = candidate.display_name or candidate.endpoint
        if item.status == "new":
            new_index += 1
            print(
                f"  {new_index}. {label} ({candidate.provider_ref}) [new]",
                file=sys.stderr,
            )
        elif item.status == "enrolled":
            print(
                f"  - {label} ({candidate.provider_ref}) "
                f"[already enrolled as {item.alias}]",
                file=sys.stderr,
            )
        else:
            print(
                f"  - {label} ({candidate.provider_ref}) "
                f"[identity changed; {item.reason}]",
                file=sys.stderr,
            )


def _select_candidates(
    input_func: InputFunc,
    candidates: tuple[DiscoveryCandidate, ...],
) -> tuple[DiscoveryCandidate, ...]:
    answer = input_func(
        "Enroll which new candidates? [comma-separated numbers, blank=skip] "
    )
    indexes: list[int] = []
    for part in answer.split(","):
        part = part.strip()
        if not part:
            continue
        index = int(part)
        if index < 1 or index > len(candidates):
            raise ValueError(f"candidate selection out of range: {index}")
        indexes.append(index - 1)
    return tuple(candidates[index] for index in indexes)


def _read_alias(input_func: InputFunc, candidate: DiscoveryCandidate) -> str:
    suggested = _suggested_alias(candidate)
    prompt = f"Alias for {candidate.endpoint}"
    if suggested:
        prompt += f" [{suggested}]"
    prompt += ": "
    alias = input_func(prompt).strip() or suggested
    if not alias:
        raise ValueError("machine alias is required")
    validate_machine_alias(alias)
    return alias


def _suggested_alias(candidate: DiscoveryCandidate) -> str:
    suggested = candidate.machine_selector.strip()
    if not suggested:
        return ""
    try:
        validate_machine_alias(suggested)
    except ValueError:
        return ""
    return suggested


def _read_bundle_once(getpass_func: GetPassFunc, stdin: TextIO) -> str:
    if not stdin.isatty():
        return stdin.read()
    return getpass_func("Paste enrollment bundle: ")


def _apply_recovery_message(alias: str) -> str:
    return (
        f"{alias}: configuration was written to the chezmoi source but is not yet "
        "applied. Retry the apply, or if the target consumed the bootstrap, issue a "
        f"new bundle and run `sase machine repair {alias}`."
    )


def _hello_recovery_message(alias: str, detail: str) -> str:
    return (
        f"{alias}: enrollment is incomplete ({detail}). The target may have consumed "
        "the one-time bootstrap. Retry, or issue a new bundle and run "
        f"`sase machine repair {alias}`."
    )


def _status_detail(status: MachineStatus | None) -> str:
    if status is None:
        return "hello returned no status"
    return status.message or status.state


__all__ = [
    "MachineInitApplyResult",
    "MachineInitPlan",
    "MachineInitService",
    "ReconciledCandidate",
]
