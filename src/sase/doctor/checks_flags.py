"""Feature-flag doctor checks: registry integrity, override hygiene, due flags."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import sase
from sase.core import time as core_time
from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.feature_flags.beads import FlagBeadSnapshot, load_flag_bead_snapshots
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.integrity import (
    IntegrityFinding,
    due_integrity_findings,
    override_integrity_findings,
    registry_integrity_findings,
)
from sase.feature_flags.managed import project_is_sase_managed
from sase.feature_flags.models import FeatureFlagDefinition, FeatureFlagSnapshot
from sase.feature_flags.orphan import checkout_base_committed_at
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.snapshot import current_flags

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


_MAX_DETAIL_ROWS = 10
_UNSET: Any = object()


def flag_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the ``flags.*`` doctor check specs."""
    return (
        CheckSpec(
            id="flags.due",
            group="flags",
            title="Overdue feature flags",
            runner=lambda: _check_flags_due(context),
        ),
        CheckSpec(
            id="flags.overrides",
            group="flags",
            title="Feature-flag override hygiene",
            runner=lambda: _check_flags_overrides(context),
        ),
        CheckSpec(
            id="flags.registry",
            group="flags",
            title="Feature-flag registry integrity",
            runner=lambda: _check_flags_registry(context),
        ),
    )


def _check_flags_registry(
    context: DoctorContext,
    *,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    beads: tuple[FlagBeadSnapshot, ...] | None | Any = _UNSET,
    is_managed: bool | None = None,
    now: datetime | None = None,
    checkout_committed_at: datetime | None | Any = _UNSET,
) -> DiagnosticCheck:
    """Both-direction registry/bead integrity."""
    resolved_managed = (
        project_is_sase_managed(context.cwd) if is_managed is None else is_managed
    )
    if not resolved_managed:
        return _check(
            "flags.registry",
            "Feature-flag registry integrity",
            "SKIP",
            "flag registry integrity is checked in SASE-managed checkouts",
            data={"is_sase_managed": False},
        )

    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    resolved_beads = load_flag_bead_snapshots(context.cwd) if beads is _UNSET else beads
    if resolved_beads is None:
        return _check(
            "flags.registry",
            "Feature-flag registry integrity",
            "WARN",
            "flag bead store is unavailable; registry/bead integrity was not verified",
            data={
                "is_sase_managed": True,
                "bead_store": None,
                "definition_count": len(resolved_definitions),
            },
            next_steps=(
                "Open a SASE-managed checkout that has a readable bead store "
                "and rerun `sase doctor -C flags.registry`.",
            ),
        )

    resolved_checkout = (
        checkout_base_committed_at(context.cwd)
        if checkout_committed_at is _UNSET
        else checkout_committed_at
    )
    findings = registry_integrity_findings(
        resolved_definitions,
        resolved_beads,
        checkout_committed_at=resolved_checkout,
        now=now,
    )
    return _findings_check(
        "flags.registry",
        "Feature-flag registry integrity",
        findings,
        ok_summary="registry and flag beads agree in both directions",
        data={
            "is_sase_managed": True,
            "definition_count": len(resolved_definitions),
            "bead_count": len(resolved_beads),
        },
    )


def _check_flags_overrides(
    context: DoctorContext,
    *,
    snapshot: FeatureFlagSnapshot | None = None,
    env_raw: str | None = None,
) -> DiagnosticCheck:
    """Unknown keys, non-booleans, scope violations, and inherited env values."""
    resolved_env = (
        context.env.get(SASE_FEATURE_FLAGS_ENV) if env_raw is None else env_raw
    )
    if snapshot is None:
        snapshot = current_flags()
    findings = override_integrity_findings(snapshot, env_raw=resolved_env)
    return _findings_check(
        "flags.overrides",
        "Feature-flag override hygiene",
        findings,
        ok_summary="no unknown, non-boolean, scoped, or inherited flag overrides",
        data={
            "env_set": resolved_env is not None,
            "diagnostic_count": len(snapshot.diagnostics),
        },
    )


def _check_flags_due(
    context: DoctorContext,
    *,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    beads: tuple[FlagBeadSnapshot, ...] | None | Any = _UNSET,
    is_managed: bool | None = None,
    today: date | None = None,
    release: str | None = None,
) -> DiagnosticCheck:
    """Overdue flags are errors here; soon-due flags warn."""
    resolved_managed = (
        project_is_sase_managed(context.cwd) if is_managed is None else is_managed
    )
    if not resolved_managed:
        return _check(
            "flags.due",
            "Overdue feature flags",
            "SKIP",
            "flag due dates are checked in SASE-managed checkouts",
            data={"is_sase_managed": False},
        )

    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    resolved_beads = load_flag_bead_snapshots(context.cwd) if beads is _UNSET else beads
    if resolved_beads is None:
        if not resolved_definitions:
            return _check(
                "flags.due",
                "Overdue feature flags",
                "OK",
                "no feature flags are registered",
                data={"is_sase_managed": True, "definition_count": 0},
            )
        return _check(
            "flags.due",
            "Overdue feature flags",
            "WARN",
            "flag bead store is unavailable; due dates were not verified",
            data={
                "is_sase_managed": True,
                "bead_store": None,
                "definition_count": len(resolved_definitions),
            },
        )

    findings = due_integrity_findings(
        resolved_definitions,
        resolved_beads,
        today=core_time.local_now().date() if today is None else today,
        release=sase.__version__ if release is None else release,
    )
    return _findings_check(
        "flags.due",
        "Overdue feature flags",
        findings,
        ok_summary="no registered feature flags are overdue",
        data={
            "is_sase_managed": True,
            "definition_count": len(resolved_definitions),
            "bead_count": len(resolved_beads),
        },
    )


def _findings_check(
    check_id: str,
    title: str,
    findings: Sequence[IntegrityFinding],
    *,
    ok_summary: str,
    data: dict[str, object],
) -> DiagnosticCheck:
    errors = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    if errors:
        status: CheckStatus = "ERROR"
        chosen = errors
        summary = f"{len(errors)} feature-flag error(s)"
    elif warnings:
        status = "WARN"
        chosen = warnings
        summary = f"{len(warnings)} feature-flag warning(s)"
    else:
        return _check(check_id, title, "OK", ok_summary, data=data)

    details = tuple(finding.message for finding in chosen[:_MAX_DETAIL_ROWS])
    payload = {
        **data,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity,
                "message": finding.message,
                "key": finding.key,
                "bead_id": finding.bead_id,
            }
            for finding in findings
        ],
    }
    return _check(
        check_id,
        title,
        status,
        summary,
        details=details,
        data=payload,
        next_steps=_next_steps(check_id, status),
    )


def _next_steps(check_id: str, status: CheckStatus) -> tuple[str, ...]:
    if check_id == "flags.due" and status == "ERROR":
        return (
            "Answer the pending FlagTriage gate, or extend the flag bead "
            "with `sase bead update <id> --remove-by <YYYY-MM-DD>/<release>`.",
        )
    if check_id == "flags.overrides":
        return (
            "Inspect `sase flag list` and clear inherited SASE_FEATURE_FLAGS, "
            "deprecated env aliases, or invalid feature_flags config values.",
        )
    if check_id == "flags.registry" and status == "WARN":
        return (
            "If this is another tree's in-flight `sase flag new`, rebase "
            "after that definition lands. Otherwise add the registry entry "
            "or close the bead.",
        )
    if check_id == "flags.registry":
        return (
            "Align the registry entry and its flag bead, then rerun "
            "`sase doctor -C flags.registry`.",
        )
    return ()


def _check(
    check_id: str,
    title: str,
    status: CheckStatus,
    summary: str,
    *,
    details: tuple[str, ...] = (),
    next_steps: tuple[str, ...] = (),
    data: dict[str, object] | None = None,
) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=check_id,
        group="flags",
        status=status,
        title=title,
        summary=summary,
        details=details,
        next_steps=next_steps,
        data=data or {},
    )


__all__ = [
    "flag_check_specs",
]
