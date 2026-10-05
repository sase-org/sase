"""Deep-only ``instructions`` doctor group for the instruction scoreboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def instructions_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the deep-only ``instructions`` check group."""
    return (
        CheckSpec(
            id="instructions.delivery",
            group="instructions",
            title="Instruction delivery matches the contract",
            runner=lambda: check_instructions_delivery(context),
            deep=True,
        ),
        CheckSpec(
            id="instructions.helpers",
            group="instructions",
            title="No helper accepted a final declaration",
            runner=lambda: check_instructions_helpers(context),
            deep=True,
        ),
    )


def check_instructions_delivery(context: DoctorContext) -> DiagnosticCheck:
    """Warn on rows that break contract 1x, project, directive, or native."""
    from sase.instructions import _runs as run_mod
    from sase.instructions.verify import build_report, collect_observations

    now = datetime.now(tz=UTC)
    scored = run_mod.enumerate_runs(
        limit_per_provider=10,
        since=now - timedelta(days=7),
        until=None,
        project=context.project,
        agent=None,
        providers=(),
    )
    if not scored:
        return DiagnosticCheck(
            id="instructions.delivery",
            group="instructions",
            status="SKIP",
            title="Instruction delivery matches the contract",
            summary="no SASE runs in the last 7 days",
        )
    observations = collect_observations(scored)
    report = build_report(scored, observations, filters={})
    offenders: list[str] = []
    for row in report.provider_rows:
        if row.provider == "agy":
            continue
        reasons: list[str] = []
        if row.contract not in ("1×", "1× [1]"):
            reasons.append(f"contract {row.contract}")
        if row.project != "✓":
            reasons.append(f"project {row.project}")
        if row.directive != "✓":
            reasons.append(f"directive {row.directive}")
        try:
            native_first = row.native_full.split("×")[0].strip()
            native_num = int(native_first) if native_first not in ("0", "◌") else 0
        except ValueError:
            native_num = 0
        if native_num > 1:
            reasons.append(f"native-full {row.native_full}")
        if reasons:
            offenders.append(f"{row.provider} ({', '.join(reasons)})")
    if offenders:
        return DiagnosticCheck(
            id="instructions.delivery",
            group="instructions",
            status="WARN",
            title="Instruction delivery matches the contract",
            summary="delivery drift: " + "; ".join(offenders),
        )
    return DiagnosticCheck(
        id="instructions.delivery",
        group="instructions",
        status="OK",
        title="Instruction delivery matches the contract",
        summary=f"{len(scored)} runs verified against the contract",
    )


def check_instructions_helpers(context: DoctorContext) -> DiagnosticCheck:
    """Warn on any accepted helper declaration or root guard denial."""
    from sase.instructions import _runs as run_mod
    from sase.instructions.verify import collect_observations

    now = datetime.now(tz=UTC)
    scored = run_mod.enumerate_runs(
        limit_per_provider=10,
        since=now - timedelta(days=7),
        until=None,
        project=context.project,
        agent=None,
        providers=(),
    )
    if not scored:
        return DiagnosticCheck(
            id="instructions.helpers",
            group="instructions",
            status="SKIP",
            title="No helper accepted a final declaration",
            summary="no SASE runs in the last 7 days",
        )
    observations = collect_observations(scored)
    accepted = sum(o.final_accepted for o in observations)
    denials = sum(1 for o in observations if o.root_guard_denial)
    if accepted or denials:
        return DiagnosticCheck(
            id="instructions.helpers",
            group="instructions",
            status="WARN",
            title="No helper accepted a final declaration",
            summary=(
                f"{accepted} accepted helper declaration(s), "
                f"{denials} root guard denial(s)"
            ),
        )
    return DiagnosticCheck(
        id="instructions.helpers",
        group="instructions",
        status="OK",
        title="No helper accepted a final declaration",
        summary="no accepted helper declarations",
    )


__all__ = [
    "check_instructions_helpers",
    "check_instructions_delivery",
    "instructions_check_specs",
]
