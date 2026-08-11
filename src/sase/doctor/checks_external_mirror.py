"""Detached-lumberjack tracker-auth check for the external issue mirror.

Doctor cannot reproduce the AXE daemon's detached environment, so this check
does not attempt an interactive provider call. It reports the mirror's own
persisted evidence instead: what the ``external_issue_mirror`` chop actually
observed the last time it ran, which is the only thing that can distinguish
"no issues" from a silent auth failure in the daemon environment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.external_mirror.auth import TrackerProbe, read_tracker_probes

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_STALE_AFTER = timedelta(minutes=30)
_NEXT_STEPS_AUTH = (
    "Run `gh auth login` in the AXE daemon's environment.",
    "Run `sase bead sync-external --dry-run` to retest interactively.",
)
_NEXT_STEPS_GENERAL = (
    "Run `sase axe chop list -a` to confirm the external_issue_mirror instances.",
    "Run `sase doctor -C axe.chops` for broader chop diagnostics.",
)


def external_mirror_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the external mirror tracker-auth check spec."""
    return (
        CheckSpec(
            id="axe.external_mirror",
            group="axe",
            title="External mirror tracker auth",
            runner=lambda: _check_external_mirror(context),
        ),
    )


def _is_mirror_chop_configured() -> bool:
    try:
        from sase.axe.chop_inventory import collect_chop_inventory

        inventory = collect_chop_inventory()
    except Exception:
        return False
    return any(
        chop.name == "external_issue_mirror" and chop.status == "configured"
        for chop in inventory.configured_chops
    )


def _enabled_project_keys() -> tuple[str, ...]:
    try:
        records = list_project_records(
            sase_projects_dir(), "enabled", include_home=False, projects_only=True
        )
    except Exception:
        return ()
    return tuple(record.project_name for record in records if record.is_project)


def _check_external_mirror(context: DoctorContext) -> DiagnosticCheck:
    del context
    if not _is_mirror_chop_configured():
        return DiagnosticCheck(
            id="axe.external_mirror",
            group="axe",
            status="SKIP",
            title="External mirror tracker auth",
            summary="external_issue_mirror is not configured",
        )

    probes = read_tracker_probes()
    chop_probes = {
        project: probe for project, probe in probes.items() if probe.source == "chop"
    }

    auth_failed = sorted(
        project
        for project, probe in chop_probes.items()
        if probe.outcome == "auth_error"
    )
    if auth_failed:
        return DiagnosticCheck(
            id="axe.external_mirror",
            group="axe",
            status="ERROR",
            title="External mirror tracker auth",
            summary=(
                f"Tracker authentication failed for {len(auth_failed)} project(s) "
                "in the detached lumberjack environment"
            ),
            details=tuple(f"auth_error: {project}" for project in auth_failed),
            next_steps=_NEXT_STEPS_AUTH,
            data={"auth_failed_projects": auth_failed},
        )

    degraded = sorted(
        project
        for project, probe in chop_probes.items()
        if probe.outcome in {"rate_limited", "unavailable"}
    )
    if degraded:
        return DiagnosticCheck(
            id="axe.external_mirror",
            group="axe",
            status="WARN",
            title="External mirror tracker auth",
            summary=(
                f"Tracker access is degraded for {len(degraded)} project(s) in the "
                "detached lumberjack environment"
            ),
            details=tuple(
                f"{chop_probes[project].outcome}: {project}" for project in degraded
            ),
            next_steps=_NEXT_STEPS_GENERAL,
            data={"degraded_projects": degraded},
        )

    enabled_projects = _enabled_project_keys()
    now = datetime.now(UTC)
    stale_or_missing = sorted(
        project
        for project in enabled_projects
        if not _has_fresh_ok_probe(chop_probes.get(project), now=now)
    )
    if stale_or_missing:
        return DiagnosticCheck(
            id="axe.external_mirror",
            group="axe",
            status="WARN",
            title="External mirror tracker auth",
            summary=(
                f"{len(stale_or_missing)} enabled project(s) have no fresh "
                "detached tracker-auth evidence"
            ),
            details=tuple(
                f"no fresh chop probe: {project}" for project in stale_or_missing
            ),
            next_steps=_NEXT_STEPS_GENERAL,
            data={"stale_or_missing_projects": stale_or_missing},
        )

    return DiagnosticCheck(
        id="axe.external_mirror",
        group="axe",
        status="OK",
        title="External mirror tracker auth",
        summary=f"Detached tracker auth is fresh for {len(enabled_projects)} project(s)",
        data={"enabled_project_count": len(enabled_projects)},
    )


def _has_fresh_ok_probe(probe: TrackerProbe | None, *, now: datetime) -> bool:
    if probe is None or probe.outcome != "ok":
        return False
    observed_at = _parse_iso(probe.observed_at)
    if observed_at is None:
        return False
    return now - observed_at <= _STALE_AFTER


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


__all__ = ["external_mirror_check_specs"]
