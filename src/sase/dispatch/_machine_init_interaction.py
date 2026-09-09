"""Terminal interaction and presentation helpers for machine init."""

from __future__ import annotations

from collections.abc import Sequence
import sys
from typing import TextIO

from sase.dispatch._machine_init_types import (
    GetPassFunc,
    InputFunc,
    ReconciledCandidate,
)
from sase.dispatch.models import (
    DispatchConfig,
    DiscoveryCandidate,
    MachineDiagnostic,
    MachineRecord,
    MachineStatus,
    validate_machine_alias,
)


def non_info_messages(config: DispatchConfig) -> tuple[str, ...]:
    return tuple(item.message for item in config.diagnostics if item.severity != "info")


def discovery_failed(diagnostics: Sequence[MachineDiagnostic]) -> bool:
    return any(item.severity == "error" for item in diagnostics)


def print_diagnostics(diagnostics: Sequence[MachineDiagnostic]) -> None:
    for diagnostic in diagnostics:
        if diagnostic.alias:
            print(
                f"{diagnostic.severity}: {diagnostic.alias}: {diagnostic.message}",
                file=sys.stderr,
            )
        else:
            print(
                f"{diagnostic.severity}: {diagnostic.message}",
                file=sys.stderr,
            )


def print_enrolled(enrolled: Sequence[MachineRecord]) -> None:
    if not enrolled:
        return
    print("Configured remote machines:", file=sys.stderr)
    for machine in enrolled:
        state = "quarantined" if machine.quarantined else "enrolled"
        print(
            f"  {machine.alias}\t{state}\t{machine.provider_ref}\t{machine.endpoint}",
            file=sys.stderr,
        )


def print_reconciled(items: Sequence[ReconciledCandidate]) -> None:
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


def select_candidates(
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


def read_alias(input_func: InputFunc, candidate: DiscoveryCandidate) -> str:
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


def read_bundle_once(getpass_func: GetPassFunc, stdin: TextIO) -> str:
    if not stdin.isatty():
        return stdin.read()
    return getpass_func("Paste enrollment bundle: ")


def apply_recovery_message(alias: str) -> str:
    return (
        f"{alias}: configuration was written to the chezmoi source but is not yet "
        "applied. Retry the apply, or if the target consumed the bootstrap, issue a "
        f"new bundle and run `sase machine repair {alias}`."
    )


def hello_recovery_message(alias: str, detail: str) -> str:
    return (
        f"{alias}: enrollment is incomplete ({detail}). The target may have consumed "
        "the one-time bootstrap. Retry, or issue a new bundle and run "
        f"`sase machine repair {alias}`."
    )


def status_detail(status: MachineStatus | None) -> str:
    if status is None:
        return "hello returned no status"
    return status.message or status.state
