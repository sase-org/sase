"""Deep-only ``instructions`` doctor group for the instruction scoreboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

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
        CheckSpec(
            id="instructions.coverage",
            group="instructions",
            title="Shadow instruction manifests cover observed sessions",
            runner=lambda: check_instructions_coverage(context),
            deep=True,
        ),
    )


def check_instructions_delivery(context: DoctorContext) -> DiagnosticCheck:
    """Warn on rows that break contract 1x, project, directive, or native."""
    from sase.instructions import run_index as run_mod
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
    from sase.instructions import run_index as run_mod
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
    accepted = sum(o.final_accepted for o in observations if o.helper_type)
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


def check_instructions_coverage(context: DoctorContext) -> DiagnosticCheck:
    """Warn on observed sessions without a shadow manifest, or shadow errors."""
    from sase.instructions import run_index as run_mod
    from sase.instructions import coverage as coverage_mod

    title = "Shadow instruction manifests cover observed sessions"
    now = datetime.now(tz=UTC)
    scored = run_mod.enumerate_runs(
        limit_per_provider=10,
        since=now - timedelta(hours=24),
        until=None,
        project=context.project,
        agent=None,
        providers=(),
    )
    records: list[coverage_mod.ManifestRecord] = []
    for run in scored:
        records.extend(coverage_mod.run_manifest_records(run.artifact_dir))
    if not records:
        return DiagnosticCheck(
            id="instructions.coverage",
            group="instructions",
            status="SKIP",
            title=title,
            summary="no shadow manifests in the last 24 hours",
        )
    known = [record.rendered_at for record in records if record.rendered_at is not None]
    earliest = min(known) if known else now
    sessions = coverage_mod.root_sessions(scored)
    verdicts = coverage_mod.cover_sessions(sessions, records)
    # Only sessions in runs that started after the earliest manifest count:
    # older runs predate the shadow hook, so their gap is expected.
    recent_uncovered = sorted(
        f"{item.run_name}/{item.session_id}"
        for item in verdicts
        if not item.covered and _run_started_after(item, scored, earliest)
    )
    errors: list[str] = []
    for run in scored:
        from sase.instructions.manifests import read_run_manifests

        for entry in read_run_manifests(run.artifact_dir):
            if entry.error is not None:
                errors.append(f"{run.name} seq {entry.seq}")
    problems: list[str] = []
    if recent_uncovered:
        problems.append("uncovered sessions: " + ", ".join(recent_uncovered))
    if errors:
        problems.append(f"{len(errors)} shadow error(s): " + ", ".join(errors[:5]))
    if problems:
        return DiagnosticCheck(
            id="instructions.coverage",
            group="instructions",
            status="WARN",
            title=title,
            summary="; ".join(problems),
        )
    return DiagnosticCheck(
        id="instructions.coverage",
        group="instructions",
        status="OK",
        title=title,
        summary=f"{len(verdicts)} sessions covered by shadow manifests",
    )


def _run_started_after(
    item: Any,
    scored: list[Any],
    earliest: datetime,
) -> bool:
    """Return whether *item*'s run started after *earliest*."""
    for run in scored:
        if run.name == item.run_name and run.started_at > earliest:
            return True
    return False


__all__ = [
    "check_instructions_coverage",
    "check_instructions_helpers",
    "check_instructions_delivery",
    "instructions_check_specs",
]
