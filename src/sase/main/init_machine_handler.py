"""Optional remote-machine enrollment for ``sase init``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import TextIO
import sys

from sase.dispatch.config import load_dispatch_config, remote_dispatch_enabled
from sase.dispatch.machine_service import MachineService
from sase.dispatch.models import DiscoveryCandidate, DispatchError

from .init_plan import InitAction, InitPlan


def plan_init_machine(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for optional remote-machine enrollment."""
    del args
    config = load_dispatch_config()
    if config.machines:
        aliases = ", ".join(machine.alias for machine in config.machines)
        return InitPlan(
            command="machine",
            label="Machine",
            summary=f"remote machines are configured: {aliases}",
            actions=(),
            warnings=_diagnostic_messages(config),
        )
    if not remote_dispatch_enabled():
        return InitPlan(
            command="machine",
            label="Machine",
            summary="remote machine enrollment is disabled by remote_dispatch",
            actions=(),
            warnings=_diagnostic_messages(config),
        )
    if not config.discovery_enabled_provider_refs:
        return InitPlan(
            command="machine",
            label="Machine",
            summary="no remote machine discovery providers are configured",
            actions=(),
            warnings=_diagnostic_messages(config),
        )
    return InitPlan(
        command="machine",
        label="Machine",
        summary="remote machine enrollment can discover configured providers",
        actions=(
            InitAction(
                path=Path("remote machine enrollment"),
                operation="validate",
                detail="discover providers and optionally enroll selected machines",
            ),
        ),
        warnings=_diagnostic_messages(config),
        requires_tty=True,
    )


def run_init_machine(args: argparse.Namespace) -> int:
    """Interactively discover and optionally enroll remote machines."""
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

    input_func: Callable[[str], str] = getattr(args, "_init_input_func", None) or input
    stdin: TextIO = getattr(args, "_init_stdin", None) or sys.stdin
    if not stdin.isatty():
        print(
            "error: remote machine enrollment requires an interactive TTY",
            file=sys.stderr,
        )
        return 1
    if not remote_dispatch_enabled():
        print(
            "remote machine enrollment is disabled by remote_dispatch.",
            file=sys.stderr,
        )
        return 1

    service = MachineService()
    try:
        candidates = service.discover()
    except DispatchError as exc:
        print(f"error: remote machine discovery failed: {exc}", file=sys.stderr)
        return 1
    if not candidates:
        print("No remote machine candidates found.")
        return 0

    _print_candidates(candidates)
    try:
        selected = _select_candidates(input_func, candidates)
    except (EOFError, KeyboardInterrupt):
        print("\nremote machine enrollment cancelled.", file=sys.stderr)
        return 1
    if not selected:
        print("No remote machines enrolled.")
        return 0

    for candidate in selected:
        try:
            alias = input_func(f"Alias for {candidate.endpoint}: ").strip()
            bundle = input_func(f"Enrollment bundle for {alias}: ")
            service.add_machine(
                alias=alias,
                endpoint=candidate.endpoint,
                provider_ref=candidate.provider_ref,
                bundle_text=bundle,
            )
        except Exception as exc:  # noqa: BLE001 - interactive command boundary.
            print(
                f"error: failed to enroll {candidate.endpoint}: {exc}",
                file=sys.stderr,
            )
            return 1
        print(f"Enrolled {alias}.")
    return 0


def handle_init_machine_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init machine``."""
    sys.exit(run_init_machine(args))


def _diagnostic_messages(config: object) -> tuple[str, ...]:
    diagnostics = getattr(config, "diagnostics", ())
    return tuple(
        item.message for item in diagnostics if getattr(item, "severity", "") != "info"
    )


def _print_candidates(candidates: tuple[DiscoveryCandidate, ...]) -> None:
    print("Remote machine candidates:")
    for index, candidate in enumerate(candidates, start=1):
        label = candidate.display_name or candidate.endpoint
        print(f"  {index}. {label} ({candidate.provider_ref})")


def _select_candidates(
    input_func: Callable[[str], str],
    candidates: tuple[DiscoveryCandidate, ...],
) -> tuple[DiscoveryCandidate, ...]:
    answer = input_func(
        "Enroll which candidates? [comma-separated numbers, blank=skip] "
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


__all__ = ["handle_init_machine_command", "plan_init_machine", "run_init_machine"]
